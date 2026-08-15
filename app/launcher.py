"""桌面壳启动器（W8，docs/03 §7）。

职责：
- 找空闲端口 → 线程内起 Uvicorn（仅监听 127.0.0.1）→ 轮询 /system/health → 打开窗口。
- 窗口关闭钩子里优雅关停：取消运行中任务 → 关浏览器 → 停服务。
- 单实例锁（Windows 命名互斥量）；崩溃日志写 logs/crash/。

pywebview 为可选依赖：未安装时退化为「起服务 + 打印地址 + 前台等待」，
便于在开发机（无 GUI 依赖）上验证启动流程。
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn

try:  # 桌面 GUI 依赖为可选，缺失时降级为无窗口模式
    import webview
except ImportError:  # pragma: no cover - 取决于运行环境是否装了 pywebview
    webview = None

# 仅 Windows 有命名互斥量；其它平台用进程锁文件兜底。
try:
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None  # type: ignore[assignment]

from autooffer_server.config import ServerConfig
from autooffer_server.main import create_app

log = logging.getLogger("autooffer.app")


def _find_free_port(preferred: int = 8765) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])


class _SingleInstance:
    """进程级单实例锁（Windows 命名互斥量 / 其它平台锁文件）。"""

    def __init__(self) -> None:
        self._handle: Any = None
        self._lock_file: Any = None

    def acquire(self) -> bool:
        if msvcrt is not None:
            import ctypes

            name = "Global\\AutoOfferDesktop"
            handle = ctypes.windll.kernel32.CreateMutexW(None, False, name)
            if handle and ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                return False
            self._handle = handle
            return True
        # 非 Windows：锁文件
        lock = Path.home() / ".autooffer" / "app.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        import fcntl

        self._lock_file = lock.open("w")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def release(self) -> None:
        if self._handle and msvcrt is not None:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None
        if self._lock_file is not None:
            with contextlib.suppress(Exception):
                self._lock_file.close()
            self._lock_file = None


def _run_server(app: Any, host: str, port: int) -> None:
    """在线程内运行 Uvicorn；进程退出时随主线程结束。"""
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    server.run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autooffer-app", description="AutoOffer 桌面壳")
    parser.add_argument("--data-dir", default=None, help="数据目录（默认 %%APPDATA%%/AutoOffer）")
    parser.add_argument("--headless", action="store_true", help="任务浏览器无头运行")
    parser.add_argument("--no-window", action="store_true", help="仅起服务不弹窗口（调试用）")
    args = parser.parse_args(argv)

    single = _SingleInstance()
    if not single.acquire():
        log.error("AutoOffer 已在运行，本次启动退出（单实例）")
        print("AutoOffer 已在运行，本次启动退出。", file=sys.stderr)
        return 1

    try:
        config = ServerConfig.create(data_dir=args.data_dir, headless=args.headless)
        app = create_app(config)
        port = _find_free_port()
        base_url = f"http://127.0.0.1:{port}"

        t = threading.Thread(target=_run_server, args=(app, config.host, port), daemon=True)
        t.start()

        # 轮询健康检查，最多等 15 秒
        import urllib.request

        for _ in range(150):
            try:
                with urllib.request.urlopen(  # noqa: S310 - 仅本机回环地址
                    f"{base_url}/api/v1/system/health", timeout=1
                ) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.1)
        else:
            log.error("本地服务启动超时")
            print("本地服务启动超时", file=sys.stderr)
            return 1

        log.info("app.ready %s", base_url)
        if args.no_window or webview is None:
            if webview is None:
                print(
                    "未安装 pywebview（pip install pywebview），以无窗口模式运行。",
                    file=sys.stderr,
                )
            print(f"AutoOffer 已启动: {base_url}")
            print("按 Ctrl+C 退出。")
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                return 0
            finally:
                single.release()

        webview.create_window("AutoOffer", base_url, width=1200, height=800)
        webview.start()
        log.info("app.window_closed")
        return 0
    finally:
        single.release()


if __name__ == "__main__":
    raise SystemExit(main())
