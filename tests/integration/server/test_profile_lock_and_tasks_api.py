"""档案乐观锁与任务 API 回归：并发保存不再 last-write-wins 静默覆盖；
任务列表 state 过滤与删除。"""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from tests.integration.server.conftest import sample_profile_payload


def _put_profile(client: TestClient, pid: str, payload: dict[str, Any], **kw: Any) -> Any:
    return client.put(
        f"/api/v1/profiles/{pid}", json={"payload": payload, **kw}
    )


def test_profile_optimistic_lock_conflict(client: TestClient) -> None:
    """旧版本凭据保存 → 409；不带凭据保持旧语义（无条件覆盖）。"""
    payload = sample_profile_payload()
    assert _put_profile(client, "p-lock", payload).status_code == 200
    v1 = client.get("/api/v1/profiles/p-lock/version").json()["updated_at"]

    # 窗口 A 用旧凭据保存（窗口 B 已先行保存推进版本）→ 409
    _put_profile(client, "p-lock", payload)  # 窗口 B：不带凭据直接保存
    resp = _put_profile(client, "p-lock", payload, expected_updated_at=v1)
    assert resp.status_code == 409, resp.text
    assert "已被其他窗口" in resp.json()["detail"]

    # 正确凭据 → 200 且返回新版本；新版本立即可用于下一次保存
    v2 = client.get("/api/v1/profiles/p-lock/version").json()["updated_at"]
    resp = _put_profile(client, "p-lock", payload, expected_updated_at=v2)
    assert resp.status_code == 200
    new_v = resp.json()["updated_at"]
    resp2 = _put_profile(client, "p-lock", payload, expected_updated_at=new_v)
    assert resp2.status_code == 200


def test_profile_version_404(client: TestClient) -> None:
    assert client.get("/api/v1/profiles/no-such/version").status_code == 404


def test_tasks_state_filter(client: TestClient) -> None:
    client.put(
        "/api/v1/profiles/p1", json={"label": "示例", "payload": sample_profile_payload()}
    )
    task_id = client.post(
        "/api/v1/tasks", json={"url": "https://example.com/apply", "profile_id": "p1"}
    ).json()["id"]

    deadline = time.time() + 8
    while time.time() < deadline:
        if client.get(f"/api/v1/tasks/{task_id}").json()["state"] == "AWAITING_REVIEW":
            break
        time.sleep(0.05)

    ids = [t["id"] for t in client.get("/api/v1/tasks", params={"state": "AWAITING_REVIEW"}).json()]
    assert task_id in ids
    ids = [t["id"] for t in client.get("/api/v1/tasks", params={"state": "RUNNING"}).json()]
    assert task_id not in ids
    # 非法状态值按无过滤处理
    assert any(
        t["id"] == task_id for t in client.get("/api/v1/tasks", params={"state": "bogus"}).json()
    )


def test_delete_task(client: TestClient) -> None:
    client.put(
        "/api/v1/profiles/p1", json={"label": "示例", "payload": sample_profile_payload()}
    )
    task_id = client.post(
        "/api/v1/tasks", json={"url": "https://example.com/apply", "profile_id": "p1"}
    ).json()["id"]

    # 活跃任务：先取消再删（FakeRunner 很快完成，两种路径都合法）
    resp = client.delete(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200 and resp.json()["deleted"] is True
    assert client.get(f"/api/v1/tasks/{task_id}").status_code == 404
    # 事件一并清理（缺失任务的事件查询返回空列表而非 404）
    assert client.get(f"/api/v1/tasks/{task_id}/events").json() == []
    # 重复删除 → 404
    assert client.delete(f"/api/v1/tasks/{task_id}").status_code == 404
