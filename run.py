#!/usr/bin/env python3
"""需求词挖掘机 · 入口

用途：抓取 Product Hunt 每日新品 → 解析每款产品的真实网站与域名 →
     罗列成清单（CSV / 看板 / Markdown），供你研究同类站点、优化自己的网站。

域名年龄、流量、关键词等"验证信号"由你用 AITDK 自行补充，本工具不做第三方 enrichment。

用法：
  python run.py                 # 默认抓取「昨天」发布的 Product Hunt 产品
  python run.py --date 2026-10-08
  python run.py --date 2026-10-08 --reparse  # 不调 PH 接口，用本地数据重解析真实网站
  python run.py --date 2026-10-08 --force    # 忽略本地缓存，强制重新请求接口
  python preview.py             # 本地打开看板（绕开浏览器缓存）

产物：
  data/<date>.json   原始结果（含全部产品网站/域名）
  data/<date>.csv    全部产品清单（Excel 友好，按票数排序，可筛选）
  data/<date>.md     人类可读日报
  data/history.json  累计历史（看板趋势 + 产品表）
  public/index.html  可直接双击打开的看板
"""
import argparse
import json
import sys
from datetime import date, timedelta

from src import config, ph_api, enrich, analyze, report


def main():
    config.ensure_dirs()
    parser = argparse.ArgumentParser(description="Product Hunt 需求词自动挖掘")
    parser.add_argument("--date", help="目标日期 YYYY-MM-DD，默认昨天")
    parser.add_argument("--force", action="store_true",
                        help="忽略本地缓存，强制重新请求 Product Hunt 接口")
    parser.add_argument("--reparse", action="store_true",
                        help="不调用 PH 接口，直接用本地已存数据重新解析真实网站")
    args = parser.parse_args()

    target = args.date or (date.today() - timedelta(days=1)).isoformat()
    after, before = ph_api.date_window(target)

    cache_file = config.STATE_DIR / f"{target}.json"

    # --reparse：复用本地产品数据，只重做"真实网站解析"这一步（省接口配额）
    if args.reparse:
        if not cache_file.is_file():
            print(f"❌ 找不到本地数据 {cache_file}，请先正常运行一次 run.py", file=sys.stderr)
            sys.exit(1)
        saved = json.loads(cache_file.read_text(encoding="utf-8"))
        nodes = _nodes_from_saved(saved)
        if not nodes:
            print("❌ 本地数据里没有产品记录，无法重解析", file=sys.stderr)
            sys.exit(1)
        print(f"[1/3] --reparse：复用 {target} 本地 {len(nodes)} 款产品，跳过 PH 接口")
        result = _resolve_and_analyze(nodes, target, cache_file)
        _summarize(target, result)
        return

    # 缓存优先：同一天的数据没必要重复请求（接口有配额限制）
    if cache_file.is_file() and not args.force:
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("products"):
                print(f"[1/3] 已存在 {target} 的本地数据，跳过接口请求"
                      f"（{cached.get('product_count', len(cached['products']))} 款产品）")
                print(f"      重新解析网站：--reparse ｜ 完全重抓：--force")
                paths = report.write_all(cached)
                _summarize(target, cached, paths)
                return
        except (OSError, ValueError):
            # 缓存损坏则忽略，走正常抓取
            pass

    print(f"[1/3] 抓取 Product Hunt {target} 发布的产品 ...")
    try:
        nodes = ph_api.fetch_posts(config.PH_API_TOKEN, after, before)
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        if "缺少 PH_API_TOKEN" in str(e):
            print("请先在 .env 或环境变量配置 PH_API_TOKEN（免费申请见 README）。",
                  file=sys.stderr)
        sys.exit(1)
    print(f"     接口返回 {len(nodes)} 款产品")

    nodes.sort(key=lambda n: n.get("votesCount", 0) or 0, reverse=True)
    nodes = nodes[: config.MAX_PRODUCTS]

    result = _resolve_and_analyze(nodes, target, cache_file)
    _summarize(target, result)


def _resolve_and_analyze(nodes: list, target: str, cache_file) -> dict:
    """解析真实网站 → 分析 → 出报告。返回分析结果。

    幂等设计（重要）：已经解析出真实网站的记录会**直接复用**，不再联网；
    只有"还没解析出来"的才需要请求。因此重复运行 --reparse 不会把好数据写坏。
    """
    print(f"[2/3] 解析 {len(nodes)} 款产品的真实网站 ...")

    keys = []          # 需要联网解析的链接（按顺序对应 nodes）
    preset = {}        # index -> 已解析好的真实网站（无需联网）
    for i, n in enumerate(nodes):
        w = (n.get("website") or "").strip()
        u = (n.get("url") or "").strip()
        raw = (n.get("ph_link") or "").strip()   # 上一次保留下来的原始 PH 链接

        if w and not enrich.is_ph_link(w):
            preset[i] = w            # 已经是真实官网，直接复用（幂等）
            keys.append("")
        elif enrich.is_ph_link(raw):
            keys.append(raw)         # 优先用保留下来的 /r/ 短链重试
        elif enrich.is_ph_link(w):
            keys.append(w)           # API 刚返回的 /r/ 短链
        else:
            keys.append(u)           # 退回 PH 产品页（可从页面内嵌 JSON 提取）

        # 记录原始 PH 链接，供以后反复重试
        n["ph_link"] = raw or w or u

    mapping = enrich.resolve_websites(keys, config.LINK_CACHE_FILE,
                                      workers=config.RESOLVE_WORKERS)
    reused = len(preset)
    resolved = 0
    for i, n in enumerate(nodes):
        real = preset.get(i) or mapping.get(keys[i])
        n["website"] = real or ""                                   # 产品真实官网
        n["url"] = enrich.strip_tracking(n.get("url") or "")        # PH 帖子页（去追踪参数）
        n["domain"] = enrich.normalize_domain(real)                 # 真实域名
        if real:
            resolved += 1
    print(f"     真实网站 {resolved}/{len(nodes)} 款"
          f"（其中 {reused} 款复用已有结果，未联网）")

    # 一条都解析不出来 = 运行环境被拦截，属于硬故障。
    # 此时必须中止：否则会把"网站列全空"的结果覆盖到已有数据并发布到看板。
    if resolved == 0 and nodes:
        print(file=sys.stderr)
        print("❌ 一条真实网站都没解析出来，已中止，避免把空网站列覆盖到已有数据。",
              file=sys.stderr)
        print("   最常见原因：当前运行环境的出口 IP 被 Product Hunt 的 Cloudflare 拦截"
              "（返回 403 挑战页，而不是 302 跳转）。", file=sys.stderr)
        print("   GitHub Actions 等机房 IP 会被拦；本机住宅网络可正常解析。",
              file=sys.stderr)
        print("   处理：在本机跑 `python run.py --date <日期> --reparse` 补全后再推送；"
              "详见 README「常见问题」。", file=sys.stderr)
        sys.exit(2)

    if resolved < len(nodes) * 0.3:
        print(f"     ⚠️ 解析率偏低（{resolved}/{len(nodes)}），可能有部分请求被拦截")

    print("[3/3] 分析需求词 + 生成报告/看板 ...")
    result = analyze.analyze(nodes, target)
    report.write_all(result)
    return result


def _nodes_from_saved(saved: dict) -> list:
    """把已保存的 JSON（products 为扁平结构）还原成 analyze 需要的 node 形态。"""
    nodes = []
    for p in saved.get("products", []) or []:
        nodes.append({
            "name": p.get("name", ""),
            "tagline": p.get("tagline", ""),
            "votesCount": p.get("votes", 0),
            "url": p.get("url", ""),
            "website": p.get("website", ""),
            "ph_link": p.get("ph_link", ""),
            "topics": {"edges": [{"node": {"name": t}} for t in (p.get("topics") or [])]},
        })
    return nodes


def _summarize(target: str, result: dict, paths: dict | None = None):
    if paths:
        print("✅ 完成。产出文件：")
        for k, v in paths.items():
            print(f"   - {k}: {v}")

    print(f"\n📋 {target} 共 {result['product_count']} 款产品，"
          f"其中 {result['website_count']} 款有真实网站")
    print("前 5 名（按票数）：")
    for p in sorted(result["products"], key=lambda r: r["votes"], reverse=True)[:5]:
        print(f"   • {p['name']}（{p['votes']} 票）{p['website'] or '（无独立站）'}")
    if result.get("top_demand_directions"):
        print("\n🔥 需求方向 Top3：")
        for c in result["top_demand_directions"][:3]:
            print(f"   • {c['topic']}（新品 {c['launches']} / 票数 {c['votes']} / "
                  f"机会分 {c['opportunity']}）")
    print(f"\n👉 数据文件：  data/{target}.csv")
    print("👉 打开看板：  python preview.py")


if __name__ == "__main__":
    main()
