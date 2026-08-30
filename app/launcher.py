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
import logging.handlers
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
    webview = None  # type: ignore[assignment]

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


def _resolve_port(data_dir: Path, cli_port: int | None = None) -> int:
    """服务端口优先级：命令行 --port > 设置页 service_port > 默认 8765。

    只在启动时读取（换监听端口必须重启服务）；返回期望端口，
    实际是否可用由 _find_free_port 兜底。
    """
    if cli_port:
        return cli_port
    from autooffer_server.services.settings import SettingsStore

    settings = SettingsStore(data_dir / "settings.json").get()
    port = settings.get("service_port", 8765)
    if isinstance(port, int) and 1024 <= port <= 65535:
        return port
    log.warning("app.port_invalid_setting value=%s fallback=8765", port)
    return 8765


def _write_runtime_info(data_dir: Path, port: int, base_url: str) -> None:
    """把实际监听地址写到数据目录，供排障与外部工具发现（端口被占自动换过时尤其重要）。"""
    import json
    import os

    path = data_dir / "server.json"
    try:
        path.write_text(
            json.dumps(
                {"port": port, "base_url": base_url, "pid": os.getpid()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        log.warning("app.runtime_info_write_failed path=%s", path)


def setup_file_logging(logs_dir: Path) -> Path:
    """全量运行日志落盘：structlog 与 uvicorn 一并写入滚动文件（2MB×5）。

    用户以 exe/无窗口方式运行时没有控制台可看，排障必须依赖这份文件。
    """
    import structlog as _structlog

    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / "app.log"
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).addHandler(handler)
    # structlog 默认直印 stdout；切到 stdlib 通道，与 uvicorn 同格式进文件
    _structlog.configure(
        processors=[
            _structlog.stdlib.add_log_level,
            _structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=_structlog.stdlib.BoundLogger,
        logger_factory=_structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    return path


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
    parser.add_argument(
        "--cdp-endpoint",
        default=None,
        help="连接用户已有浏览器（CDP），如 http://127.0.0.1:9222；操作当前打开的页面",
    )
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="主窗口启动后最小化（静默待命，操作用户浏览器当前页面）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="本地服务监听端口（优先于设置页；默认 8765，被占用时自动换空闲端口）",
    )
    args = parser.parse_args(argv)

    single = _SingleInstance()
    if not single.acquire():
        log.error("AutoOffer 已在运行，本次启动退出（单实例）")
        print("AutoOffer 已在运行，本次启动退出。", file=sys.stderr)
        return 1

    try:
        config = ServerConfig.create(
            data_dir=args.data_dir, headless=args.headless, cdp_endpoint=args.cdp_endpoint
        )
        log_path = setup_file_logging(Path(config.data_dir) / "logs")
        log.info("app.logging file=%s", log_path)
        app = create_app(config)
        preferred = _resolve_port(Path(config.data_dir), args.port)
        port = _find_free_port(preferred)
        config.port = port  # health 端点等对外报告实际监听端口
        base_url = f"http://127.0.0.1:{port}"
        _write_runtime_info(Path(config.data_dir), port, base_url)
        if port != preferred:
            log.warning(
                "app.port_conflict preferred=%s actual=%s（如需固定端口请在设置页更换）",
                preferred,
                port,
            )
        log.info("app.listening %s", base_url)

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

        window = webview.create_window("AutoOffer", base_url, width=1200, height=800)
        if args.minimized and window is not None:

            def _minimize_on_loaded() -> None:
                with contextlib.suppress(Exception):
                    window.minimize()

            window.events.loaded += _minimize_on_loaded
        webview.start()
        log.info("app.window_closed")
        return 0
    finally:
        single.release()


if __name__ == "__main__":
    raise SystemExit(main())
