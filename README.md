# 🔍 需求词挖掘机（Demand Miner）

全自动从 **Product Hunt** 每日新品中，抓取产品 → **解析每款产品的真实网站与域名** → 罗列成清单（CSV / 看板 / Markdown），并附上「需求方向 + 长尾需求词」，帮你研究同类站点、优化自己的网站。

> 逻辑链：**每天抓前一天 PH 新品 → 解析真实网站 / 域名 → 罗列全部产品清单 → 聚合需求方向 + 长尾词 → 出看板**

**关于「域名年龄 / 流量 / 关键词」**：这部分验证信号由你用 **AITDK 自行补充**，本工具**不再内置** RDAP / SimilarWeb 调用（之前 8000+ 的域名年龄就是 RDAP 对老域名的注册日期，对"找需求词"没用且干扰判断，已移除）。本工具只负责最关键的「拿到产品 + 解析真实网站 + 罗列清单」。

---

## 一、它能产出什么

| 输出 | 含义 | 用途 |
|---|---|---|
| 📋 **全部产品清单（CSV）** | 当天每款产品的名称 / 真实网站 / 域名 / 票数 / 话题，按票数排序 | **核心交付**：Excel 直接打开，逐站研究、优化自己网站 |
| 🔥 需求方向（Top 15） | 按 PH 官方 topic 聚合，含新品数 / 总票数 / 机会分 | 选大赛道，看哪个方向最热 |
| 🎯 长尾需求词（Top 25） | 从产品 tagline 提取的痛点词 / 功能词 | 直接当产品定位、落地页标题 |
| 机会分（0-100） | 票数 + 出现密度综合打分 | 一眼看出值不值得做 |

> **「票数」是什么？** 就是 Product Hunt 上该产品在发布当天获得的 **upvote（点赞）数**（`votesCount`）。票数越高 = 越多 PH 用户觉得它有价值，等于这个需求方向被市场验证的强度。需求方向排序、机会分都基于它。

### 真实网站是怎么拿到的？

Product Hunt 的 API 返回的 `website` 字段**不是**产品官网，而是站内跳转短链
（形如 `https://www.producthunt.com/r/Y54VBVRLNCMW2B`）。所以工具会做三级解析：

| 级别 | 手段 | 说明 |
|---|---|---|
| A | 跟随 `/r/XXXX` 的 301 跳转 | 最快、最准，正常情况走这条 |
| B | 抓 PH 产品页内嵌 JSON 的 `websiteUrl` | 短链失效时兜底 |
| C | 普通重定向跟随 | 最后兜底 |

- 解析结果会去掉 `utm_*` / `ref` 等追踪参数，并缓存到 `data/.link_cache.json`，重复运行不再联网。
- **解析失败不写缓存**，下次运行会重试——不会因为一次网络抖动就永久拿不到。
- 原始 PH 链接会保存在 JSON 的 `ph_link` 字段，因此 `--reparse` 可以**反复重试**。
- 确实没有独立站的产品（如纯 iOS App），`真实网站` 列为空，属正常。

---

## 二、本地运行

### 1. 准备密钥（只需一个）

```bash
cp .env.example .env
```

- **PH_API_TOKEN（必填，免费）**
  打开 https://www.producthunt.com/v2/oauth/applications → New Application → 复制页面底部的 **Developer Token**。
  （应用表单的 Redirect URI 随便填 `https://localhost/callback` 即可，Developer Token 流程用不到回调。）

### 2. 安装 & 运行

```bash
pip install -r requirements.txt

# 默认抓「昨天」
python run.py

# 指定某天
python run.py --date 2026-10-08

# 已经抓过、只想重新解析"真实网站"（不消耗 PH 接口配额）
python run.py --date 2026-10-08 --reparse

# 忽略本地数据，强制重新请求接口
python run.py --date 2026-10-08 --force
```

> **同一天的数据会自动缓存**：`data/<date>.json` 已存在时默认不再请求接口（PH 有配额限制），
> 直接复用本地数据重出报告。需要重抓用 `--force`，只想重解析网站用 `--reparse`。

### 3. 查看结果

- `data/<日期>.csv` —— **首选**：全部产品清单，Excel 直接打开，可筛选/排序（含真实网站链接）
- `public/index.html` —— 看板，点开某天后有「📋 全部产品」表（真实网站可点击）
- `data/<日期>.md` —— 当日可读报告（含完整产品表）
- `data/<日期>.json` —— 原始结构化数据（含完整产品清单）

**推荐的打开方式（避免浏览器缓存看到旧快照）：**

```bash
python preview.py
```

会自动起一个本地服务器并打开浏览器（禁用了缓存）。停止按 `Ctrl + C`。

> 也可以直接**双击 `public/index.html`** —— 数据已内嵌在文件里，无需联网、无需服务器。
> 但如果重跑过 `run.py`，旧标签页不会自动更新，需按 **Ctrl + F5** 强制刷新
> （页头「快照生成于 …」时间戳可用来确认是否最新）。

---

## 三、全自动部署（GitHub Actions，零服务器成本）

1. 把本目录推到 GitHub 仓库。
2. 仓库 **Settings → Secrets and variables → Actions** 中添加 `PH_API_TOKEN`。
3. **Actions → 每日需求词挖掘 → Enable**。
4. 之后每天 UTC 01:00（≈北京 09:00）自动跑，结果 commit 回仓库。

> 想立刻看效果？在 Actions 页面点 **Run workflow** 手动触发一次。

**可选：把看板变成公开网页** —— 仓库 **Settings → Pages** 选 `main` 分支的 `/public` 目录。

---

## 四、目录结构

```
demand-miner/
├── run.py                 # 入口：编排 抓取 → 解析域名 → 分析 → 出报告
├── preview.py             # 本地预览看板（起服务器 + 打开浏览器，禁用缓存）
├── src/
│   ├── config.py          # 环境变量 / .env 解析 / 目录配置
│   ├── ph_api.py          # Product Hunt v2 GraphQL 客户端（含限流自动重试）
│   ├── enrich.py          # 仅保留 网站→域名 解析工具（验证信号由你用 AITDK 补充）
│   ├── analyze.py         # 需求方向 + 长尾词提取 + 机会评分 + 完整产品清单
│   └── report.py          # CSV / Markdown / JSON / HTML 看板生成
├── data/                  # 每日产出（自动生成）
├── public/index.html      # 看板（自动生成）
├── .github/workflows/     # 每日自动化
└── requirements.txt
```

---

## 五、常见问题

**Q：打开 `127.0.0.1:8777` 报 `ERR_EMPTY_RESPONSE` / 无法访问？**
说明本地预览服务器没在运行（临时起的服务器关掉后就没了）。用 `python preview.py` 重新起一个，
或直接双击 `public/index.html`。

> ⚠️ 注意：如果 8777 被占用（例如上一个服务没退干净），`preview.py` 会**自动顺延到 8778、8779…**，
> 请以它打印出来的 `访问地址` 为准，不要固守 8777。想固定端口用 `python preview.py --port 9000`。

**Q：为什么打开看板看不到产品列表？**
按顺序排查：
1. **脚本执行失败**：若页面只有标题外框、没有任何数字，按 **F12** 看控制台是否有红色报错。本项目曾在脚本里写 `const top = ...`（`window.top` 是浏览器内置属性，重名会导致整段脚本不执行）；现已修复并加了生成阶段静态校验 `_assert_no_global_collision()`。
2. **浏览器缓存**：重跑 `run.py` 后按 **Ctrl + F5**；页头时间戳对得上即最新。用 `python preview.py` 可彻底绕开。
3. **真的没数据**：看板会直接提示「还没有任何数据 · 先运行 python run.py」。

**Q：`PH_API_TOKEN` 明明填了 `.env`，却报「缺少 PH_API_TOKEN」？**
早期版本依赖 `python-dotenv`，该库未安装时会**静默失败**。现已改为内置解析器（`src/config.py` 的
`_load_dotenv`），**无需任何第三方库**即可读取 `.env`，不装依赖也不会失效。
另外检查：`.env` 要放在**项目根目录**，写法是 `PH_API_TOKEN=xxxxx`（等号两侧不要加引号或空格）。

**Q：报 `HTTP 429 Too Many Requests` / 提示触发限流？**
这是 Product Hunt 接口的**配额限制**，不是 token 失效。响应头会给出精确状态：
`x-rate-limit-limit` / `x-rate-limit-remaining` / `x-rate-limit-reset`（多少秒后重置，通常 ≤15 分钟）。
本工具会自动读取 `reset` 并等待重试（最长 20 分钟）。若仍失败，等十几分钟再跑即可。
另外：同一天的 JSON 已存在时会**默认跳过接口请求**，直接复用本地数据重新出报告，避免重复消耗配额；
要强制重抓加 `--force`。

**Q：抓取不到产品？**
- 确认 `PH_API_TOKEN` 有效（401 会在日志明确报错）。
- 有些日期 PH 发布量少甚至为 0（如周末/节假日），属正常。

**Q：我想自己用 AITDK 补充流量/年龄/关键词，怎么接？**
本工具只产出「产品 + 真实网站 + 域名」清单（`data/<日期>.csv` 里就有域名列）。你把这批域名直接丢进你的 AITDK 工具做批量核查即可，无需改本工具代码。
