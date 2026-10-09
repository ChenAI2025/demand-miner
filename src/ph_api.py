"""Product Hunt v2 GraphQL 客户端：按日期拉取当日/指定日发布的 products。

API 文档：https://api.producthunt.com/v2/docs
鉴权：Bearer Developer Token（免费，无需 OAuth）
速率：官方约 900 次请求/15 分钟；超限会返回 HTTP 429，这里自动退避重试。
"""
import time

import requests

PH_ENDPOINT = "https://api.producthunt.com/v2/api/graphql"

MAX_RETRIES = 4          # 限流/临时故障最大重试次数
BACKOFF_BASE = 5         # 指数退避基数（秒）：5 → 10 → 20 → 40
MAX_WAIT = 1200          # 单次最长等待（秒）；超过则直接报错，不再空等

# 拉取指定时间窗内发布的产品；按票数排序，便于后续截取 Top N
POSTS_QUERY = """
query DailyPosts($after: DateTime!, $before: DateTime!, $first: Int!, $cursor: String) {
  posts(postedAfter: $after, postedBefore: $before, order: VOTES, first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        name
        tagline
        votesCount
        url
        website
        createdAt
        topics(first: 4) {
          edges { node { name slug } }
        }
      }
    }
  }
}
"""


def fetch_posts(token: str, after: str, before: str, page_size: int = 50):
    """分页拉取 [after, before) 时间窗内发布的产品，返回 list[dict]（node 层）。"""
    if not token:
        raise RuntimeError("缺少 PH_API_TOKEN，无法调用 Product Hunt API")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    all_nodes = []
    cursor = None
    while True:
        variables = {
            "after": after,
            "before": before,
            "first": page_size,
            "cursor": cursor,
        }
        resp = _post_with_retry(headers, variables, page_size)
        if resp.status_code == 401:
            raise RuntimeError("PH_API_TOKEN 无效或已过期（HTTP 401）")
        resp.raise_for_status()
        payload = resp.json()
        if "errors" in payload:
            raise RuntimeError(f"Product Hunt 返回错误：{payload['errors']}")

        posts = payload["data"]["posts"]
        for edge in posts["edges"]:
            all_nodes.append(edge["node"])

        if not posts["pageInfo"]["hasNextPage"]:
            break
        cursor = posts["pageInfo"]["endCursor"]

    return all_nodes


def _post_with_retry(headers: dict, variables: dict, page_size: int) -> requests.Response:
    """带退避的 POST；专门处理 429（限流）与 5xx（临时故障）。

    Product Hunt 会在响应头里给出精确的配额状态，尽量据此等待而不是盲目重试：
      x-rate-limit-limit / x-rate-limit-remaining / x-rate-limit-reset(秒)
    429 常见于短时间内多次运行或共享出口 IP，通常在 reset 后自然恢复。
    """
    last = None
    for attempt in range(MAX_RETRIES + 1):
        resp = requests.post(
            PH_ENDPOINT,
            json={"query": POSTS_QUERY, "variables": variables},
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            last = resp
            if attempt >= MAX_RETRIES:
                break

            wait = None
            if resp.status_code == 429:
                # 服务端告知的配额与重置时间优先
                remaining = resp.headers.get("x-rate-limit-remaining", "?")
                reset_in = resp.headers.get("x-rate-limit-reset")
                print(f"     ⏳ 触发限流（剩余配额 {remaining}）")
                try:
                    wait = float(reset_in) + 2 if reset_in else None
                except ValueError:
                    wait = None

            if wait is None:
                ra = resp.headers.get("Retry-After")
                if ra:
                    try:
                        wait = float(ra)
                    except ValueError:
                        wait = None
            if wait is None:
                wait = BACKOFF_BASE * (2 ** attempt)

            if wait > MAX_WAIT:
                break
            print(f"     ⏳ {wait:.0f}s 后自动重试 ({attempt + 1}/{MAX_RETRIES}) ...")
            time.sleep(wait)
            continue
        return resp

    if last is not None and last.status_code == 429:
        reset_in = last.headers.get("x-rate-limit-reset", "未知")
        raise RuntimeError(
            "Product Hunt 接口限流（HTTP 429），自动等待后仍失败。\n"
            f"     建议 {reset_in} 秒后再运行（配额约每 15 分钟重置一次）。"
        )
    return last


def date_window(target_date: str):
    """根据 YYYY-MM-DD 生成 PH 的 postedAfter/postedBefore 时间窗（UTC）。"""
    after = f"{target_date}T00:00:00Z"
    y, m, d = map(int, target_date.split("-"))
    # 简单日期 +1 计算（覆盖月末/年末）
    from datetime import date, timedelta
    nxt = date(y, m, d) + timedelta(days=1)
    before = f"{nxt.isoformat()}T00:00:00Z"
    return after, before
