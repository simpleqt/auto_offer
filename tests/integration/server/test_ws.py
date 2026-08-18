"""WebSocket 事件流集成测试（docs/03 §5.2）。"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.integration.server.conftest import FakeRunner, sample_profile_payload


def collect(ws: Any, *, limit: int = 12) -> list[dict[str, Any]]:
    """读取若干事件，遇到 report/终态即停。"""
    out: list[dict[str, Any]] = []
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") == "ping":
            continue
        out.append(msg)
        if msg.get("type") == "report":
            break
        if msg.get("type") == "state" and msg.get("value") == "AWAITING_REVIEW":
            break
    return out


def test_ws_streams_events_and_final_state(client: TestClient) -> None:
    client.put("/api/v1/profiles/p1", json={"payload": sample_profile_payload()})
    task_id = client.post(
        "/api/v1/tasks", json={"url": "https://example.com/apply", "profile_id": "p1"}
    ).json()["id"]

    with client.websocket_connect(f"/ws/tasks/{task_id}") as ws:
        events = collect(ws)

    kinds = [e.get("type") for e in events]
    assert "step" in kinds or "state" in kinds
    summaries = " ".join(str(e.get("summary", "")) for e in events)
    states = [e.get("value") for e in events if e.get("type") == "state"]
    # 事件流应体现执行过程或最终状态之一（时序取决于连接建立时机）
    assert "填写姓名" in summaries or "拆分区块" in summaries or "AWAITING_REVIEW" in states


def test_ws_replays_history_for_late_subscriber(client: TestClient) -> None:
    """任务已结束后再连接：应能回放历史事件与当前状态。"""
    import time

    client.put("/api/v1/profiles/p1", json={"payload": sample_profile_payload()})
    task_id = client.post(
        "/api/v1/tasks", json={"url": "https://example.com/apply", "profile_id": "p1"}
    ).json()["id"]

    deadline = time.time() + 8
    while time.time() < deadline:
        if client.get(f"/api/v1/tasks/{task_id}").json()["state"] == "AWAITING_REVIEW":
            break
        time.sleep(0.05)

    with client.websocket_connect(f"/ws/tasks/{task_id}") as ws:
        events = collect(ws)

    assert events, "迟到订阅者应收到历史回放"
    text = " ".join(str(e.get("summary", "")) + str(e.get("value", "")) for e in events)
    assert "AWAITING_REVIEW" in text or "报告生成" in text


def test_ws_waiting_human_state_pushed(ctx_factory: Any) -> None:
    from autooffer_server.main import create_app

    runner = FakeRunner(pause_reason="检测到验证码，请手动完成")
    with TestClient(create_app(ctx=ctx_factory(runner))) as c:
        c.put("/api/v1/profiles/p1", json={"payload": sample_profile_payload()})
        task_id = c.post(
            "/api/v1/tasks", json={"url": "https://x.com", "profile_id": "p1"}
        ).json()["id"]

        with c.websocket_connect(f"/ws/tasks/{task_id}") as ws:
            found = False
            for _ in range(12):
                msg = ws.receive_json()
                if msg.get("type") == "state" and msg.get("value") == "WAITING_HUMAN":
                    assert "验证码" in msg.get("reason", "")
                    found = True
                    break
            assert found, "应推送 WAITING_HUMAN 状态与原因"
