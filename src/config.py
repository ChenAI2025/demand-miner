"""全局配置：从环境变量 / .env 读取，集中管理密钥与运行参数。"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """极简 .env 解析器（不依赖 python-dotenv，避免"库没装就静默失效"）。

    规则：
    - 已存在的环境变量优先（GitHub Actions secrets 不会被本地 .env 覆盖）
    - 支持 # 注释、KEY=VALUE、值两端引号
    - 解析失败不抛错，但会在下方校验阶段暴露出来
    """
    if not path.is_file():
        return
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="ignore")
    except OSError:
        return
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


# 先加载 .env，再统一读取（避免"库缺失 → 静默读不到密钥"这类问题）
_load_dotenv(PROJECT_ROOT / ".env")

PH_API_TOKEN = os.getenv("PH_API_TOKEN", "").strip()

# 本工具只负责"拿到产品 + 解析真实网站"。域名年龄/流量/关键词等验证信号
# 由你用 AITDK 自行补充，因此不再内置 SIMILARWEB / AITDK 等密钥配置。

MAX_PRODUCTS = int(os.getenv("MAX_PRODUCTS", "60"))

# 产物目录（可被环境变量覆盖，便于 CI 写入仓库）
STATE_DIR = Path(os.getenv("STATE_DIR", str(PROJECT_ROOT / "data")))
PUBLIC_DIR = Path(os.getenv("PUBLIC_DIR", str(PROJECT_ROOT / "public")))

HISTORY_FILE = STATE_DIR / "history.json"
DASHBOARD_FILE = PUBLIC_DIR / "index.html"

# 「PH 跳转短链 → 真实官网」的解析缓存，避免重复联网解析
LINK_CACHE_FILE = STATE_DIR / ".link_cache.json"

# 解析真实网站时的并发数（Product Hunt 会限流，不宜过高）
RESOLVE_WORKERS = int(os.getenv("RESOLVE_WORKERS", "4"))


def ensure_dirs():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
