#!/usr/bin/env python3
"""诊断脚本：在 GitHub runner 上探测哪种方式能把 producthunt.com/r/XXXX
解析成真实官网。

背景：本机（住宅 IP）用最简 UA 跟随重定向即可成功，但 GitHub runner
（机房 IP）上 100% 失败，疑似被 Product Hunt 前面的 Cloudflare 挑战页拦截。
本脚本只做诊断、不写任何数据文件。

用法：python probe.py
"""
import sys
from urllib.parse import quote

import requests

# 取自 2026-10-09 的 Top 产品短链（Zernio / Busabase）
LINKS = [
    "https://www.producthunt.com/r/2QQY2FLJ5IUZ2E",
    "https://www.producthunt.com/r/NCFRPHEHNAHLX7",
]

MINIMAL = {"User-Agent": "Mozilla/5.0"}

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

BROWSER = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Cache-Control": "max-age=0",
}


def describe(tag, resp):
    """打印一次响应的关键信息（状态码 / 跳转链 / 最终地址 / 是否挑战页）。"""
    if resp is None:
        print(f"  [{tag}] 请求异常")
        return
    body = (resp.text or "")[:400].lower()
    challenge = ("just a moment" in body or "cf-chl" in body
                 or "security verification" in body or "captcha" in body)
    print(f"  [{tag}] HTTP {resp.status_code} | 跳转 {len(resp.history)} 次 "
          f"| 最终: {resp.url}")
    if challenge:
        print("        >>> 命中 Cloudflare 挑战页")
    elif resp.history:
        print(f"        跳转链首跳 Location: "
              f"{resp.history[0].headers.get('location')}")


def probe_http(link):
    print("\n" + "=" * 76)
    print("目标:", link)
    print("=" * 76)

    # S1 现有方案：最简 UA
    try:
        describe("S1 最简UA",
                 requests.get(link, headers=MINIMAL, timeout=25, allow_redirects=True))
    except requests.RequestException as e:
        print("  [S1 最简UA] 异常:", repr(e)[:140])

    # S2 完整浏览器头
    try:
        describe("S2 浏览器头",
                 requests.get(link, headers=BROWSER, timeout=25, allow_redirects=True))
    except requests.RequestException as e:
        print("  [S2 浏览器头] 异常:", repr(e)[:140])

    # S3 Session 预热（最简 UA）——先访问首页拿 __cf_bm cookie
    for tag, hdrs in (("S3 预热-最简UA", MINIMAL), ("S4 预热-浏览器头", BROWSER)):
        try:
            s = requests.Session()
            s.headers.update(hdrs)
            warm = s.get("https://www.producthunt.com/", timeout=25)
            print(f"  [{tag}] 预热 HTTP {warm.status_code}, cookies={list(s.cookies.keys())}")
            describe(tag, s.get(link, timeout=25, allow_redirects=True))
        except requests.RequestException as e:
            print(f"  [{tag}] 异常:", repr(e)[:140])

    # S5 HEAD（只取 Location，不下载正文）
    try:
        r = requests.head(link, headers=MINIMAL, timeout=25, allow_redirects=False)
        print(f"  [S5 HEAD] HTTP {r.status_code} | Location: {r.headers.get('location')}")
    except requests.RequestException as e:
        print("  [S5 HEAD] 异常:", repr(e)[:140])

    # S6 Jina Reader（服务端渲染）
    try:
        r = requests.get("https://r.jina.ai/" + link, timeout=60)
        head = (r.text or "")[:220].replace("\n", " ｜ ")
        print(f"  [S6 Jina] HTTP {r.status_code} | {head}")
    except requests.RequestException as e:
        print("  [S6 Jina] 异常:", repr(e)[:140])

    # S7 AllOrigins（会回报最终 URL）
    try:
        r = requests.get("https://api.allorigins.win/get?url=" + quote(link, safe=""),
                         timeout=60)
        print(f"  [S7 AllOrigins] HTTP {r.status_code} | {(r.text or '')[:220]}")
    except requests.RequestException as e:
        print("  [S7 AllOrigins] 异常:", repr(e)[:140])


def probe_playwright(link):
    """S8：用真 Chromium 访问，看能否自动过 Cloudflare 挑战并落到真实站点。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [S8 Playwright] 未安装，跳过")
        return
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent=BROWSER_UA, locale="en-US",
                viewport={"width": 1366, "height": 900},
            )
            page = ctx.new_page()
            page.goto(link, wait_until="domcontentloaded", timeout=45000)

            final = page.url
            for _ in range(14):                      # 最多等约 21 秒过挑战
                if "producthunt.com" not in final:
                    break
                page.wait_for_timeout(1500)
                final = page.url

            ok = "producthunt.com" not in final
            print(f"  [S8 Playwright] 最终 URL: {final}  {'✅ 成功' if ok else '❌ 仍被拦'}")
            try:
                print(f"        title: {page.title()!r}")
            except Exception:
                pass
            browser.close()
    except Exception as e:
        print("  [S8 Playwright] 异常:", repr(e)[:200])


def main():
    print(f"Python: {sys.version.split()[0]}")
    print(f"requests: {requests.__version__}")
    for link in LINKS:
        probe_http(link)
    print("\n" + "=" * 76)
    print("Part B：真浏览器（Playwright + Chromium）")
    print("=" * 76)
    probe_playwright(LINKS[0])


if __name__ == "__main__":
    main()
