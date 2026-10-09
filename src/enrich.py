"""数据解析工具：

1. 把产品链接规整成纯域名（供你后续在 AITDK 里批量核查）
2. 解析 Product Hunt 的跳转短链，拿到产品的**真实官网**

为什么要解析短链：
  Product Hunt v2 API 返回的 `website` 字段现在是 `https://www.producthunt.com/r/XXXX`
  这样的站内跳转短链，不是产品真实官网。直接用它无法做任何外部分析，
  因此这里跟随 301 拿到真实外部地址（顺便去掉 utm/ref 等追踪参数）。

域名年龄（RDAP）、流量、核心关键词（SimilarWeb / AITDK）等"验证信号"
由你用 AITDK 自行补充，本模块不涉及。
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

import requests

_PH_HOST = "producthunt.com"
_PH_SELF_HOSTS = {"producthunt.com", "www.producthunt.com", "api.producthunt.com"}

# 需要剔除的追踪参数前缀
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_EXACT = {"ref", "ref_src", "source", "fbclid", "gclid", "mc_cid", "mc_eid"}

# 注意：这里刻意使用**最简 UA**。实测带上完整的浏览器 UA/Accept/Language 组合
# 反而会被 Product Hunt 前面的 Cloudflare 判定为可疑请求并返回 403，
# 而最简 `Mozilla/5.0` 能正常 200 跟随重定向。改动前请先实测。
_HEADERS = {
    "User-Agent": "Mozilla/5.0",
}

_429_MAX_RETRY = 2      # 网页请求遇 429 的重试次数
_429_BACKOFF = 6        # 每次重试等待秒数（6 → 12）


def _get(url: str, timeout: int, allow_redirects: bool, retry: int = _429_MAX_RETRY):
    """带 429 退避重试的 GET。Product Hunt 对网页请求也会限流。"""
    resp = None
    for attempt in range(retry + 1):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=timeout,
                                allow_redirects=allow_redirects)
        except requests.RequestException:
            return None
        if resp.status_code != 429:
            return resp
        if attempt < retry:
            time.sleep(_429_BACKOFF * (attempt + 1))
    return resp


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def is_ph_link(url: str) -> bool:
    """判断是否为 Product Hunt 站内链接（含 /r/ 跳转短链）。"""
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    return host == _PH_HOST or host.endswith("." + _PH_HOST)


def strip_tracking(url: str) -> str:
    """去掉 utm_* / ref 等追踪参数，保留其余查询串。"""
    if not url:
        return url
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith(_TRACKING_PREFIXES)
            and k.lower() not in _TRACKING_EXACT]
    return urlunparse(parts._replace(query=urlencode(kept)))


def normalize_domain(value: str) -> str | None:
    """从 url 中规整出纯域名（去协议、去 path、去 www.）。

    例：'https://www.Notion.so/path?x=1' -> 'notion.so'
    无法解析或属于 PH 站内的，返回 None。
    """
    if not value:
        return None
    v = value.strip().lower()
    if v.startswith("http://"):
        v = v[7:]
    elif v.startswith("https://"):
        v = v[8:]
    v = v.split("/")[0].split("?")[0]
    if v.startswith("www."):
        v = v[4:]
    if not v or v in _PH_SELF_HOSTS:
        return None
    return v or None


# ---------------------------------------------------------------------------
# 真实网站解析
# ---------------------------------------------------------------------------
def resolve_real_website(link: str, timeout: int = 20) -> str | None:
    """把 PH 链接解析成产品真实官网；解析不出则返回 None。

    三级兜底（越前面越准、越快）：
      A. `/r/XXXX` 跳转短链 → 直接跟随 301 拿真实地址
      B. PH 产品页 → 从页面内嵌 JSON 提取 `websiteUrl` / `redirectPath`
      C. 普通跟随重定向兜底

    - 非 PH 链接：原样返回（去掉追踪参数）
    - 最终仍停留在 producthunt.com：视为"无独立站"，返回 None
    """
    if not link:
        return None

    if not is_ph_link(link):
        return strip_tracking(link) or None

    # A. 跳转短链：一次重定向就拿到真实地址
    if "/r/" in (urlparse(link).path or ""):
        real = _follow_redirect(link, timeout)
        if real:
            return real

    # B. 产品页：页面内嵌 JSON 里有权威的 websiteUrl
    real = _scrape_product_page(link, timeout)
    if real:
        return real

    # C. 兜底
    return _follow_redirect(link, timeout)


def _follow_redirect(link: str, timeout: int) -> str | None:
    """跟随重定向；若最终仍在 producthunt.com 内则返回 None。"""
    resp = _get(link, timeout, allow_redirects=True)
    if resp is None:
        return None

    final = resp.url or ""
    if not final or is_ph_link(final):
        return None
    return strip_tracking(final) or None


def _scrape_product_page(page_url: str, timeout: int) -> str | None:
    """从 PH 产品页的内嵌 JSON 中提取真实官网。

    产品页 HTML 里带有 `"websiteUrl":"https://xxx"`（权威字段），
    另有 `"redirectPath":"/r/XXXX"` 与 `"websiteDomain":"xxx"` 可用于兜底。
    """
    resp = _get(page_url, timeout, allow_redirects=True)
    if resp is None or resp.status_code != 200:
        return None

    html = resp.text

    # B1. websiteUrl（最权威）
    m = re.search(r'"websiteUrl"\s*:\s*"(https?://[^"]+)"', html)
    if m:
        cand = m.group(1).replace("\\/", "/")
        if not is_ph_link(cand):
            return strip_tracking(cand) or None

    # B2. redirectPath → /r/XXXX
    m = re.search(r'"redirectPath"\s*:\s*"(/r/[A-Za-z0-9]+)"', html)
    if m:
        real = _follow_redirect("https://www.producthunt.com" + m.group(1), timeout)
        if real:
            return real

    # B3. websiteDomain
    m = re.search(r'"websiteDomain"\s*:\s*"([^"]+)"', html)
    if m:
        dom = m.group(1).strip()
        if dom and _PH_HOST not in dom and " " not in dom:
            return f"https://{dom}"

    return None


def resolve_websites(links: list, cache_file: Path | None = None,
                     workers: int = 8, verbose: bool = True) -> dict:
    """批量解析（并发 + 本地缓存），返回 {原链接: 真实网站或 None}。

    缓存可避免重复请求：同一条 PH 短链只解析一次，之后直接命中。
    """
    cache = {}
    if cache_file and cache_file.is_file():
        try:
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}

    todo = [u for u in dict.fromkeys(links) if u and u not in cache]
    if todo:
        if verbose:
            print(f"     需解析 {len(todo)} 条链接（已缓存 {len(cache)} 条）...")
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(resolve_real_website, u): u for u in todo}
            for fut in as_completed(futures):
                u = futures[fut]
                try:
                    cache[u] = fut.result()
                except Exception:
                    cache[u] = None
                done += 1
                if verbose and (done % 20 == 0 or done == len(todo)):
                    print(f"     已解析 {done}/{len(todo)}")

        if cache_file:
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                # 只持久化成功结果：解析失败（网络抖动等）下次运行会重试，
                # 不会被一条 None 永久"钉死"。
                persist = {k: v for k, v in cache.items() if v}
                cache_file.write_text(json.dumps(persist, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
            except OSError:
                pass

    return {u: cache.get(u) for u in links}
