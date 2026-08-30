"""桌面壳启动器（app/launcher.py）纯逻辑单元测试。

GUI 窗口与 Windows 命名互斥量依赖真实桌面环境，无法离线覆盖；
此处聚焦可脱离 GUI 验证的辅助函数。
"""

from __future__ import annotations

import logging
import socket
from pathlib import Path

import structlog
from app.launcher import _find_free_port, setup_file_logging


def test_find_free_port_returns_preferred_when_available() -> None:
    preferred = 18765
    port = _find_free_port(preferred)
    assert port == preferred


def test_find_free_port_returns_alternative_when_occupied() -> None:
    preferred = 18766
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", preferred))
        blocker.listen(1)
        port = _find_free_port(preferred)
    assert port != preferred
    # 返回的端口应当也是可绑定的空闲端口
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))


def test_find_free_port_is_loopback_safe() -> None:
    """返回端口仅应绑定回环地址（本地服务安全约束）。"""
    port = _find_free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))


def test_setup_file_logging_writes_structlog_and_stdlib(tmp_path: Path) -> None:
    """文件日志：structlog 与 uvicorn/stdlib 记录都写入滚动文件。"""
    path = setup_file_logging(tmp_path / "logs")
    assert path.exists()
    slog = structlog.get_logger("test.structlog")
    slog.info("server.started", data_dir=str(tmp_path))
    logging.getLogger("uvicorn.error").error("fake uvicorn failure")
    for h in logging.getLogger().handlers[:]:
        h.flush()
    content = path.read_text(encoding="utf-8")
    assert "server.started" in content
    assert "fake uvicorn failure" in content
