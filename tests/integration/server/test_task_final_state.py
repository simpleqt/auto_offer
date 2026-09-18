"""任务终态映射回归：runner 的 FAILED/DONE 不得一律报成 AWAITING_REVIEW。

此前终态只埋在报告 note 字符串里，scheduler 拿到正常返回就无条件置
AWAITING_REVIEW——Planner 判败/超步数/token 超限的任务在列表里显示
「等待人工审核」，状态语义两套且矛盾。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from autooffer_server.config import ServerConfig
from autooffer_server.context import AppContext
from autooffer_server.main import create_app
from tests.integration.server.conftest import FakeRunner, MemoryKeyStore, sample_profile_payload


def _wait_terminal(client: TestClient, task_id: str, timeout_s: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = client.get(f"/api/v1/tasks/{task_id}").json()
        if last.get("state") in {"AWAITING_REVIEW", "DONE", "FAILED", "CANCELLED"}:
            return last
        time.sleep(0.05)
    return last


def _make_client(tmp_path: Path, runner: FakeRunner) -> TestClient:
    config = ServerConfig.create(tmp_path / "data", headless=True)
    ctx = AppContext(config, runner=runner, keystore=MemoryKeyStore())
    app = create_app(ctx=ctx)
    return TestClient(app, base_url="http://127.0.0.1")


def _create_task(client: TestClient) -> str:
    client.put(
        "/api/v1/profiles/p1", json={"label": "示例", "payload": sample_profile_payload()}
    )
    return client.post(
        "/api/v1/tasks", json={"url": "https://example.com/apply", "profile_id": "p1"}
    ).json()["id"]


def test_runner_failed_maps_to_task_failed(tmp_path: Path) -> None:
    runner = FakeRunner(final_state="FAILED")
    with _make_client(tmp_path, runner) as client:
        task_id = _create_task(client)
        task = _wait_terminal(client, task_id)
        assert task["state"] == "FAILED", task
        assert task["wait_reason"], task
        # 报告仍正常入库供查看
        assert task["report"], task


def test_runner_done_maps_to_task_done(tmp_path: Path) -> None:
    runner = FakeRunner(final_state="DONE")
    with _make_client(tmp_path, runner) as client:
        task_id = _create_task(client)
        task = _wait_terminal(client, task_id)
        assert task["state"] == "DONE", task


def test_runner_without_final_state_still_awaits_review(tmp_path: Path) -> None:
    """旧报告/无终态字段：保持原 AWAITING_REVIEW 语义（兼容）。"""
    runner = FakeRunner()
    with _make_client(tmp_path, runner) as client:
        task_id = _create_task(client)
        task = _wait_terminal(client, task_id)
        assert task["state"] == "AWAITING_REVIEW", task
