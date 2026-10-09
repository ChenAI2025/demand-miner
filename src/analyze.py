"""需求词分析层：把 Product Hunt 产品列表转换成「可落地的需求词 + 证据」。

两路输出：
  A. 需求方向（按 PH 官方 topic 聚合）——告诉你今天哪个大赛道在密集出新。
  B. 长尾需求词（从产品 tagline 中提取）——具体的痛点/功能词，可直接拿来做产品。

同时**完整保留逐条产品清单**（名称 / 真实网站 / 域名 / 票数 / 话题），
便于你直接罗列出来研究、优化自己的网站。

注意：域名年龄、流量、关键词等"验证信号"由你用 AITDK 自行补充，
本工具只负责"拿到产品 + 解析真实网站"，不做第三方 enrichment。
"""
import math
import re
from collections import defaultdict

STOPWORDS = set("""
a an the and or but if then of to in on for with at by from as is are was were be been being
it its this that these those we you they he she them our your their my i me us do does did
have has had will would can could should may might must not no yes so just only also more most
new your get using use used uses make makes made build builds building tool tools app apps ai
all any each both few many much one two three out up down off over under again about into than
your you're we're i'm don't can't won't it's that's what's how to's
""".split())

# 常见无意义后缀词，提取长尾词时剔除
NOISE_TAIL = set(["tool", "app", "ai", "platform", "solution", "software", "builder",
                  "assistant", "generator", "agent", "api", "free", "online", "best"])
# 通用动词，单独成词或构成短语时噪声较大，剔除
VERB_NOISE = set(["turn", "turns", "turning", "make", "makes", "making", "get", "gets",
                  "build", "builds", "building", "use", "uses", "using", "help", "helps",
                  "create", "creates", "creating", "find", "finds", "finding", "write",
                  "writes", "writing", "manage", "manages", "managing", "track", "tracks",
                  "automate", "automates", "generate", "generates", "generating",
                  "let", "lets", "your", "you", "into", "with", "for", "from",
                  "more", "book", "books", "that", "this", "these", "their", "them",
                  "our", "out", "up", "off", "over", "all", "any", "one"])


def _topics_of(node: dict):
    edges = node.get("topics", {}).get("edges", [])
    return [e["node"]["name"] for e in edges if e.get("node", {}).get("name")]


def _tokenize(text: str):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", " ", text)
    toks = [t for t in text.split() if t and t not in STOPWORDS and len(t) > 2]
    return toks


# ---------------------------------------------------------------------------
# A. 需求方向（topic 聚合）
# ---------------------------------------------------------------------------
def build_clusters(products: list) -> list:
    clusters = defaultdict(lambda: {"topic": "", "launches": 0, "votes": 0, "products": []})
    for p in products:
        for t in _topics_of(p):
            c = clusters[t]
            c["topic"] = t
            c["launches"] += 1
            c["votes"] += p.get("votesCount", 0) or 0
            c["products"].append(p.get("name", ""))

    result = []
    for t, c in clusters.items():
        result.append({
            "topic": t,
            "launches": c["launches"],
            "votes": c["votes"],
            "sample_products": c["products"][:5],
        })
    result.sort(key=lambda x: (x["votes"], x["launches"]), reverse=True)
    return result


# ---------------------------------------------------------------------------
# B. 长尾需求词（从 tagline 提取）
# ---------------------------------------------------------------------------
def build_phrases(products: list) -> list:
    uni = defaultdict(lambda: {"count": 0, "votes": 0, "products": []})
    bi = defaultdict(lambda: {"count": 0, "votes": 0, "products": []})

    for p in products:
        tagline = p.get("tagline") or ""
        name = p.get("name", "")
        votes = p.get("votesCount", 0) or 0
        toks = _tokenize(tagline)
        clean = [t for t in toks if t not in NOISE_TAIL and t not in VERB_NOISE]
        for t in clean:
            uni[t]["count"] += 1
            uni[t]["votes"] += votes
            if name not in uni[t]["products"]:
                uni[t]["products"].append(name)
        for i in range(len(clean) - 1):
            phrase = f"{clean[i]} {clean[i+1]}"
            bi[phrase]["count"] += 1
            bi[phrase]["votes"] += votes
            if name not in bi[phrase]["products"]:
                bi[phrase]["products"].append(name)

    items = []
    for src, kind in ((uni, "unigram"), (bi, "bigram")):
        for phrase, d in src.items():
            if kind == "unigram":
                keep = d["count"] >= 2 or d["votes"] >= 200
            else:
                # 二元组：必须跨 >=2 款产品出现，过滤跨概念拼接噪声；
                # 或单次但票数极高（>=300）的强短语
                keep = d["count"] >= 2 or d["votes"] >= 300
            if keep:
                items.append({
                    "phrase": phrase,
                    "kind": kind,
                    "count": d["count"],
                    "votes": d["votes"],
                    "sample_products": d["products"][:4],
                })
    items.sort(key=lambda x: (x["count"], x["votes"]), reverse=True)
    return items


# ---------------------------------------------------------------------------
# 机会评分（0-100，越高越值得做）
#   验证强度（票数）+ 出现密度（新品数）
#   注：不再使用域名年龄 / 流量作为因子（那些信号由你用 AITDK 自行补充）。
# ---------------------------------------------------------------------------
def opportunity_score(launches: int, votes: int) -> int:
    v = min(100, int(math.log10(max(votes, 1) + 1) / math.log10(5000) * 60))
    d = min(40, launches * 6)
    return min(100, v + d)


def analyze(products: list, target_date: str) -> dict:
    clusters = build_clusters(products)
    phrases = build_phrases(products)

    for c in clusters:
        c["opportunity"] = opportunity_score(c["launches"], c["votes"])
    clusters.sort(key=lambda x: x["opportunity"], reverse=True)

    # 逐条产品清单：只保留"研究网站"需要的字段（轻量、可嵌入看板）
    product_rows = [{
        "name": p.get("name", ""),
        "tagline": p.get("tagline", "") or "",
        "url": p.get("url", "") or "",          # Product Hunt 帖子链接
        "website": p.get("website", "") or "",  # 产品真实外部网站
        "domain": p.get("domain") or "",
        "votes": p.get("votesCount", 0) or 0,
        "topics": _topics_of(p),
        # 原始 PH 链接（可能是 /r/ 跳转短链）。保留它才能让 --reparse 反复重试，
        # 不会因为一次解析失败就把线索永久丢掉。
        "ph_link": p.get("ph_link", "") or "",
    } for p in products]

    website_count = sum(1 for r in product_rows if r["website"])

    return {
        "date": target_date,
        "product_count": len(products),
        "website_count": website_count,
        "clusters": clusters,
        "phrases": phrases,
        "products": product_rows,
        "top_demand_directions": clusters[:15],
        "top_phrases": phrases[:25],
    }
