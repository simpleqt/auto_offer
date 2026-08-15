"""桌面壳启动器（app/launcher.py）纯逻辑单元测试。

GUI 窗口与 Windows 命名互斥量依赖真实桌面环境，无法离线覆盖；
此处聚焦可脱离 GUI 验证的辅助函数。
"""

from __future__ import annotations

import socket

from app.launcher import _find_free_port


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
