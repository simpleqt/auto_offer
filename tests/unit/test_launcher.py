"""桌面壳启动器（app/launcher.py）纯逻辑单元测试。

GUI 窗口与 Windows 命名互斥量依赖真实桌面环境，无法离线覆盖；
此处聚焦可脱离 GUI 验证的辅助函数。
"""

from __future__ import annotations

import logging
import socket
from pathlib import Path

import structlog
from app.launcher import _find_free_port, _icon_path, _resolve_port, setup_file_logging


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


def test_resolve_port_priority_cli_over_settings(tmp_path: Path) -> None:
    """命令行 --port 最高优先：设置页存了别的端口也不生效。"""
    (tmp_path / "settings.json").write_text(
        '{"service_port": 9100}', encoding="utf-8"
    )
    assert _resolve_port(tmp_path, cli_port=9200) == 9200


def test_resolve_port_from_settings(tmp_path: Path) -> None:
    """无命令行参数时读设置页配置的端口。"""
    (tmp_path / "settings.json").write_text(
        '{"service_port": 9100}', encoding="utf-8"
    )
    assert _resolve_port(tmp_path) == 9100


def test_resolve_port_defaults_and_invalid(tmp_path: Path) -> None:
    """无设置 → 默认 8765；设置值越界/类型错误 → 回退默认而不是崩溃。"""
    assert _resolve_port(tmp_path) == 8765
    (tmp_path / "settings.json").write_text(
        '{"service_port": 80}', encoding="utf-8"
    )
    assert _resolve_port(tmp_path) == 8765
    (tmp_path / "settings.json").write_text(
        '{"service_port": "not-a-port"}', encoding="utf-8"
    )
    assert _resolve_port(tmp_path) == 8765


def test_icon_path_exists_and_loadable() -> None:
    """品牌 ico 存在且 Win32 LoadImageW 能加载（标题栏图标设置的可行前提）。"""
    import sys

    icon = _icon_path()
    if sys.platform != "win32":
        assert icon is None
        return
    assert icon is not None and icon.exists(), "assets/brand/autooffer.ico 缺失"
    import ctypes

    user32 = ctypes.windll.user32
    hicon = user32.LoadImageW(None, str(icon), 1, 32, 32, 0x10)
    assert hicon, "LoadImageW 加载 ico 失败"
