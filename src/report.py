"""报告层：把分析结果落盘为 Markdown 报告 + JSON 数据 + CSV 清单 + 可直接打开的 HTML 看板。

核心交付：一份**可罗列全部产品真实网站**的清单（CSV / 看板表格 / Markdown 表），
方便你逐站研究、优化自己的网站。
"""
import csv
import datetime
import json
import re
from pathlib import Path

from . import config

# 浏览器 window 上已存在的内置属性。在全局作用域用 const/let/var 与它们重名，
# 会抛 SyntaxError 且**整段 <script> 拒绝执行**，页面表现为「结构正常但数据全空」。
_RESERVED_GLOBALS = {
    "top", "parent", "self", "window", "document", "name", "status", "length",
    "location", "history", "frames", "origin", "closed", "event", "external",
    "opener", "screen", "navigator", "console", "globalThis", "performance",
    "crypto", "localStorage", "sessionStorage", "menubar", "toolbar",
}


def _assert_no_global_collision(html: str):
    """静态检查 <script> 内顶层声明是否与 window 内置属性重名。

    历史上的真实故障：脚本里有 `const top = ...`，因 window.top 已存在而使整个
    脚本解析失败，看板静默空白。这里在生成阶段就拦下来，避免再次发生。
    """
    m = re.search(r"<script>(.*?)</script>", html, re.S)
    if not m:
        return
    script = m.group(1)
    depth = 0
    i = 0
    while i < len(script):
        ch = script[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0 and ch in ("c", "l", "v"):
            d = re.match(r"(const|let|var)\s+([A-Za-z_$][\w$]*)", script[i:])
            if d:
                name = d.group(2)
                if name in _RESERVED_GLOBALS:
                    raise RuntimeError(
                        f"看板脚本顶层变量名 '{name}' 与浏览器 window 内置属性冲突，"
                        f"会导致整段脚本不执行、页面数据全空。请改用其它变量名。"
                    )
                i += d.end()
                continue
        i += 1


# ---------------------------------------------------------------------------
# 1) 每日原始 JSON（含完整产品清单）
# ---------------------------------------------------------------------------
def save_daily_json(result: dict):
    path = config.STATE_DIR / f"{result['date']}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 2) 每日 CSV 清单（Excel 友好，按票数降序，可直接筛选/排序）
# ---------------------------------------------------------------------------
def save_csv(result: dict):
    path = config.STATE_DIR / f"{result['date']}.csv"
    rows = sorted(result.get("products", []), key=lambda r: r.get("votes", 0), reverse=True)
    # utf-8-sig：Excel 打开中文不乱码
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["排名", "产品名称", "真实网站", "域名", "票数", "话题", "一句话简介", "Product Hunt 链接"])
        for i, r in enumerate(rows, 1):
            w.writerow([
                i,
                r.get("name", ""),
                r.get("website", "") or "—",
                r.get("domain", "") or "—",
                r.get("votes", 0),
                "、".join(r.get("topics", [])),
                r.get("tagline", ""),
                r.get("url", ""),
            ])
    return path


# ---------------------------------------------------------------------------
# 3) 历史累计（用于看板趋势 + 产品表）
# ---------------------------------------------------------------------------
def load_history() -> list:
    if config.HISTORY_FILE.exists():
        try:
            return json.loads(config.HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def update_history(result: dict):
    history = load_history()
    history = [h for h in history if h.get("date") != result["date"]]
    summary = {
        "date": result["date"],
        "product_count": result["product_count"],
        "website_count": result["website_count"],
        "top_directions": [
            {"topic": c["topic"], "launches": c["launches"], "votes": c["votes"],
             "opportunity": c["opportunity"]}
            for c in result["clusters"][:10]
        ],
        "top_phrases": [p["phrase"] for p in result["phrases"][:15]],
        # 完整产品清单，供看板渲染
        "products": sorted(result["products"], key=lambda r: r.get("votes", 0), reverse=True),
    }
    history.append(summary)
    history.sort(key=lambda x: x["date"])
    config.HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return history


# ---------------------------------------------------------------------------
# 4) Markdown 报告
# ---------------------------------------------------------------------------
def _products_table_md(products: list, limit: int = None) -> str:
    rows = sorted(products, key=lambda r: r.get("votes", 0), reverse=True)
    if limit:
        rows = rows[:limit]
    lines = ["| # | 产品 | 真实网站 | 域名 | 票数 | 话题 |",
             "|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        site = r.get("website") or "—"
        lines.append(
            f"| {i} | {r.get('name','')} | {site} | {r.get('domain','') or '—'} | "
            f"{r.get('votes',0)} | {'、'.join(r.get('topics',[]))} |"
        )
    return "\n".join(lines)


def generate_markdown(result: dict) -> str:
    lines = []
    lines.append(f"# 需求词挖掘日报 · {result['date']}\n")
    lines.append(f"- 当日抓取产品数：**{result['product_count']}**")
    lines.append(f"- 其中带真实网站的产品：**{result['website_count']}**（其余多为 PH 站内产品，无独立站）")
    lines.append("")

    lines.append("## 🔥 Top 需求方向（按 PH topic 聚合）\n")
    lines.append("| 需求方向 | 新品数 | 总票数 | 机会分 | 代表产品 |")
    lines.append("|---|---|---|---|---|")
    for c in result["top_demand_directions"]:
        sample = "、".join(c["sample_products"][:3])
        lines.append(f"| {c['topic']} | {c['launches']} | {c['votes']} | {c['opportunity']} | {sample} |")
    lines.append("")

    lines.append("## 🎯 Top 长尾需求词（从产品 tagline 提取）\n")
    lines.append("| 需求词 | 出现次数 | 关联票数 | 类型 | 代表产品 |")
    lines.append("|---|---|---|---|---|")
    for p in result["top_phrases"]:
        sample = "、".join(p["sample_products"][:2])
        lines.append(f"| {p['phrase']} | {p['count']} | {p['votes']} | {p['kind']} | {sample} |")
    lines.append("")

    lines.append("## 📋 全部产品清单（含真实网站，按票数排序）\n")
    lines.append(_products_table_md(result["products"]))
    lines.append("")
    lines.append("> 完整可筛选版本见同目录 `data/%s.csv`（Excel 直接打开）。" % result["date"])
    lines.append("")
    lines.append("## 💡 如何用来优化你的网站\n")
    lines.append("1. 打开 CSV / 上表，逐一点开「真实网站」，研究同类新站的**首页结构、卖点文案、CTA、视觉风格**。")
    lines.append("2. 从 **Top 需求方向** 找你所在赛道，看高机会分方向的共性打法。")
    lines.append("3. 从 **Top 长尾需求词** 借力 —— 直接作为你落地页标题 / 板块小标题。")
    lines.append("4. 域名 / 流量 / 关键词等深度信号，用你自己的 AITDK 工具补充核查。")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5) HTML 看板（自包含，双击即可打开）
# ---------------------------------------------------------------------------
def generate_dashboard(history: list) -> str:
    data_json = json.dumps(history, ensure_ascii=False)
    generated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<title>需求词挖掘机 · 看板</title>
<style>
  :root{ --bg:#f6f8fb; --card:#fff; --ink:#1f2933; --sub:#6b7280; --line:#e5e7eb;
         --accent:#2563eb; --hot:#ef4444; --ok:#10b981; }
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
       background:var(--bg);color:var(--ink);line-height:1.6}
  header{background:linear-gradient(120deg,#2563eb,#7c3aed);color:#fff;padding:28px 24px}
  header h1{margin:0;font-size:22px}
  header p{margin:6px 0 0;opacity:.9;font-size:13px}
  header p.stamp{margin:8px 0 0;font-size:12px;opacity:.75}
  main{max-width:1080px;margin:0 auto;padding:20px}
  .cards{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 18px;flex:1;min-width:150px}
  .card .n{font-size:26px;font-weight:700}
  .card .l{font-size:12px;color:var(--sub)}
  section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:18px}
  section h2{margin:0 0 12px;font-size:16px}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
  th{color:var(--sub);font-weight:600}
  .badge{display:inline-block;background:#eef2ff;color:var(--accent);border-radius:6px;padding:1px 8px;font-size:12px;margin:1px}
  .pill{font-weight:700}
  .hot{color:var(--hot)} .ok{color:var(--ok)}
  .muted{color:var(--sub);font-size:12px}
  .runsel{margin-bottom:12px}
  select{font-size:14px;padding:6px 10px;border:1px solid var(--line);border-radius:8px}
  a{color:var(--accent);text-decoration:none}
  a:hover{text-decoration:underline}
  .prod-table td:nth-child(2){min-width:200px}
  .prod-table td:nth-child(3){word-break:break-all}
</style>
</head>
<body>
<header>
  <h1>🔍 需求词挖掘机</h1>
  <p>Product Hunt 每日新品 → 解析真实网站 → 罗列清单供你研究优化站点</p>
  <p class="stamp">快照生成于 __GENERATED__ · 共 __COUNT__ 天数据</p>
</header>
<main>
  <div class="cards" id="cards"></div>

  <section>
    <h2>选择某一天查看明细</h2>
    <div class="runsel"><select id="runPicker"></select></div>
    <div id="detail"></div>
  </section>

  <section>
    <h2>需求方向趋势（按日累计）</h2>
    <div id="trend"></div>
  </section>
</main>

<script>
const HISTORY = __DATA__;

function fmt(n){ return n==null ? "—" : n; }
function esc(s){ return (s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

// 概览卡片：最新一天
const latest = HISTORY.length ? HISTORY[HISTORY.length-1] : null;
const cards = [
  {n: HISTORY.length, l:"累计运行天数"},
  {n: latest ? latest.product_count : 0, l:"最新一天抓取产品"},
  {n: latest ? latest.website_count : 0, l:"有真实网站"},
  {n: latest ? latest.top_directions.length : 0, l:"最新需求方向数"},
];
document.getElementById("cards").innerHTML = HISTORY.length
  ? cards.map(c=>`<div class="card"><div class="n">${c.n}</div><div class="l">${c.l}</div></div>`).join("")
  : '<div class="card" style="flex-basis:100%"><div class="n" style="font-size:16px">还没有任何数据</div><div class="l">先在项目根目录运行 python run.py 生成数据，再按 Ctrl+F5 强制刷新本页</div></div>';

// 日期选择器
const picker = document.getElementById("runPicker");
picker.disabled = !HISTORY.length;
picker.innerHTML = HISTORY.length
  ? HISTORY.slice().reverse().map(r=>
      `<option value="${r.date}">${r.date}（${r.product_count} 款 / ${r.website_count} 站）</option>`).join("")
  : '<option>暂无数据</option>';

function renderDetail(date){
  const r = HISTORY.find(x=>x.date===date);
  if(!r){ document.getElementById("detail").innerHTML="<p class='muted'>无数据</p>"; return; }
  let h = `<p class="muted">${r.date} · ${r.product_count} 款产品 · ${r.website_count} 款有真实网站</p>`;
  h += `<h3 style="font-size:14px;margin:10px 0 6px">🔥 Top 需求方向</h3><table>
    <tr><th>方向</th><th>新品</th><th>票数</th><th>机会分</th></tr>`;
  r.top_directions.forEach(d=>{
    h += `<tr><td><b>${esc(d.topic)}</b></td><td>${d.launches}</td><td>${d.votes}</td>
          <td class="pill ${d.opportunity>=60?'hot':(d.opportunity>=40?'ok':'')}">${d.opportunity}</td></tr>`;
  });
  h += `</table>`;
  if(r.top_phrases && r.top_phrases.length){
    h += `<h3 style="font-size:14px;margin:14px 0 6px">🎯 长尾需求词</h3><div>`;
    h += r.top_phrases.map(p=>`<span class="badge">${esc(p)}</span>`).join("") + `</div>`;
  }
  if(r.products && r.products.length){
    h += `<h3 style="font-size:14px;margin:14px 0 6px">📋 全部产品（按票数排序，真实网站可点击）</h3><table class="prod-table">
      <tr><th>#</th><th>产品</th><th>真实网站</th><th>域名</th><th>票数</th><th>话题</th></tr>`;
    r.products.forEach((p,idx)=>{
      const site = p.website ? `<a href="${esc(p.website)}" target="_blank" rel="noopener">${esc(p.website)}</a>` : '<span class="muted">—</span>';
      h += `<tr><td>${idx+1}</td>
        <td><b>${esc(p.name)}</b><br><span class="muted">${esc(p.tagline||'')}</span></td>
        <td>${site}</td>
        <td class="muted">${esc(p.domain||'—')}</td>
        <td>${p.votes}</td>
        <td class="muted">${esc((p.topics||[]).join('、'))}</td></tr>`;
    });
    h += `</table>`;
  }
  document.getElementById("detail").innerHTML = h;
}
picker.addEventListener("change", e=>renderDetail(e.target.value));
if(latest){
  renderDetail(latest.date);
}else{
  document.getElementById("detail").innerHTML =
    "<p class='muted'>运行一次 python run.py 后，这里会显示当天的 Top 需求方向、长尾词与全部产品清单。</p>";
}

// 趋势：汇总所有天出现过的需求方向，取累计票数 Top 8
const acc = {};
HISTORY.forEach(r=>{
  r.top_directions.forEach(d=>{
    const a = acc[d.topic] || (acc[d.topic]={topic:d.topic,launches:0,votes:0,days:0});
    a.launches += d.launches; a.votes += d.votes; a.days += 1;
  });
});
const trendTop = Object.values(acc).sort((a,b)=>b.votes-a.votes).slice(0,8);
let t = `<table><tr><th>需求方向</th><th>累计新品</th><th>累计票数</th><th>出现天数</th></tr>`;
trendTop.forEach(d=>{ t += `<tr><td><b>${esc(d.topic)}</b></td><td>${d.launches}</td><td>${d.votes}</td><td class="muted">${d.days}</td></tr>`; });
t += `</table>`;
document.getElementById("trend").innerHTML = trendTop.length ? t : "<p class='muted'>暂无数据，累计趋势会在第二次运行后出现。</p>";
</script>
</body>
</html>"""
    html = html.replace("__DATA__", data_json)
    html = html.replace("__GENERATED__", generated)
    html = html.replace("__COUNT__", str(len(history)))
    _assert_no_global_collision(html)
    return html


def write_all(result: dict):
    """一次性写出 JSON / CSV / 历史 / Markdown / 看板。"""
    config.ensure_dirs()
    paths = {}
    paths["daily_json"] = str(save_daily_json(result))
    paths["csv"] = str(save_csv(result))
    history = update_history(result)
    md = generate_markdown(result)
    md_path = config.STATE_DIR / f"{result['date']}.md"
    md_path.write_text(md, encoding="utf-8")
    paths["markdown"] = str(md_path)
    dashboard = generate_dashboard(history)
    config.DASHBOARD_FILE.write_text(dashboard, encoding="utf-8")
    paths["dashboard"] = str(config.DASHBOARD_FILE)
    paths["history"] = str(config.HISTORY_FILE)
    return paths
