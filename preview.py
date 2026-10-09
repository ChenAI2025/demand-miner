#!/usr/bin/env python3
"""本地预览看板：一条命令启动静态服务器并打开浏览器。

为什么需要它：
  public/index.html 是「数据内嵌的快照」，直接双击也能看，但浏览器缓存有时会
  让你看到旧版本。用这个脚本从 http://127.0.0.1 打开可以彻底绕开缓存问题。

用法：
  python preview.py            # 默认端口 8777，自动打开浏览器
  python preview.py --port 9000
  python preview.py --no-open  # 只起服务，不自动开浏览器
  python preview.py --root .   # 以项目根为站点根（默认以 public/ 为根）

按 Ctrl + C 停止服务。
"""
import argparse
import functools
import http.server
import socket
import sys
import threading
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_ROOT = PROJECT_ROOT / "public"


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """静态文件处理器：禁用缓存，避免看到旧快照。"""

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, fmt, *args):
        # 只保留简洁日志，避免刷屏
        sys.stderr.write("  %s\n" % (fmt % args))


def find_free_port(preferred: int) -> int:
    """优先用首选端口；被占用则向后顺延，最多试 20 个。"""
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"端口 {preferred}~{preferred + 19} 都被占用，请用 --port 指定其它端口")


def main():
    parser = argparse.ArgumentParser(description="本地预览看板")
    parser.add_argument("--port", type=int, default=8777, help="端口，默认 8777")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--root", default=str(DEFAULT_ROOT),
                        help="站点根目录，默认 public/（传入 . 即项目根）")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    index = root / "index.html"

    if not root.is_dir():
        print(f"❌ 目录不存在：{root}", file=sys.stderr)
        sys.exit(1)

    print("=" * 56)
    if not index.is_file():
        print("⚠️  还没生成看板（找不到 index.html）")
        print("   请先运行：  python run.py")
        print("   生成后重新执行本脚本即可。")
        print("=" * 56)
        sys.exit(2)

    port = find_free_port(args.port)
    url = f"http://127.0.0.1:{port}/"

    handler = functools.partial(NoCacheHandler, directory=str(root))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print("🔍 需求词挖掘机 · 看板预览")
        print(f"   站点根目录：{root}")
        print(f"   访问地址：  {url}")
        print("   停止服务：  Ctrl + C")
        print("=" * 56)

        if not args.no_open:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n👋 已停止预览服务")


if __name__ == "__main__":
    main()
