"""本机回环防线回归：Host 与 Origin 双校验。

- Host：防 DNS rebinding（HTTP 与 WebSocket 通道都拦）。
- Origin：防恶意网页跨站写——浏览器对跨站简单请求（无预检的
  resume/cancel/multipart 上传）必带真实 Origin 且不可伪造；
  本机进程不发 Origin，不受影响。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def test_http_rejects_non_loopback_host(client: TestClient) -> None:
    resp = client.get("/api/v1/tasks", headers={"host": "evil.example.com"})
    assert resp.status_code == 403


def test_http_allows_loopback_host(client: TestClient) -> None:
    resp = client.get("/api/v1/tasks", headers={"host": "127.0.0.1:8765"})
    assert resp.status_code == 200


def test_ws_rejects_non_loopback_host(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/ws/tasks/t1", headers={"host": "evil.example.com"}
        ):
            pass


def test_ws_allows_loopback_host(client: TestClient) -> None:
    """合法 Host 的 WS 正常握手（能进入上下文即握手成功，无需读事件）。"""
    with client.websocket_connect(
        "/ws/tasks/t1", headers={"host": "127.0.0.1:8765"}
    ):
        pass


def test_mutating_request_rejects_website_origin(client: TestClient) -> None:
    """恶意网页跨站触发副作用（简单请求无预检）→ 403。"""
    resp = client.post(
        "/api/v1/tasks",
        json={"url": "https://example.com/apply", "profile_id": "p1"},
        headers={"origin": "https://evil.example.com"},
    )
    assert resp.status_code == 403


def test_mutating_request_rejects_null_origin(client: TestClient) -> None:
    """沙箱 iframe 的 Origin: null 可被攻击者构造 → 拒绝。"""
    resp = client.post(
        "/api/v1/tasks",
        json={"url": "https://example.com/apply", "profile_id": "p1"},
        headers={"origin": "null"},
    )
    assert resp.status_code == 403


def test_mutating_request_allows_extension_and_loopback_origin(
    client: TestClient,
) -> None:
    """插件 SW（chrome-extension://）与桌面 UI 同源（回环任意端口）放行；
    本机进程不带 Origin（TestClient 默认）也不受限——只挡跨站写。"""
    for origin in (
        "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
        "http://127.0.0.1:8765",
        "http://localhost:5173",
    ):
        resp = client.post(
            "/api/v1/tasks",
            json={"url": "https://example.com/apply", "profile_id": "p1"},
            headers={"origin": origin},
        )
        assert resp.status_code != 403, (origin, resp.status_code)

    resp = client.post(
        "/api/v1/tasks", json={"url": "https://example.com/apply", "profile_id": "p1"}
    )
    assert resp.status_code != 403


def test_get_with_website_origin_not_blocked(client: TestClient) -> None:
    """读请求由 SOP/CORS 兜底（响应跨源不可读），不在此拦。"""
    resp = client.get("/api/v1/tasks", headers={"origin": "https://evil.example.com"})
    assert resp.status_code == 200


def test_ws_rejects_website_origin(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/ws/tasks/t1",
            headers={"host": "127.0.0.1:8765", "origin": "https://evil.example.com"},
        ):
            pass
