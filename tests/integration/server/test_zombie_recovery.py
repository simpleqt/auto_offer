"""僵尸任务清理回归：服务重启后遗留的活跃态任务必须被置为 CANCELLED。

队列、resume gate 与 asyncio 任务都在内存，重启即丢——不清理则
QUEUED/RUNNING/WAITING_HUMAN 永久悬挂在任务列表，既不执行也无法 resume。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from autooffer_server.main import create_app
from tests.integration.server.conftest import FakeRunner


def test_stale_active_tasks_cancelled_on_startup(ctx_factory: Any, tmp_path: Path) -> None:
    ctx = ctx_factory(FakeRunner())
    app = create_app(ctx=ctx)

    # 模拟上次进程遗留的库状态：活跃三态 + 已完结
    asyncio.run(ctx.repo.create_task("z-queued", "https://example.com", "p1"))
    asyncio.run(ctx.repo.create_task("z-running", "https://example.com", "p1"))
    asyncio.run(ctx.repo.update_task("z-running", state="RUNNING"))
    asyncio.run(ctx.repo.create_task("z-waiting", "https://example.com", "p1"))
    asyncio.run(
        ctx.repo.update_task("z-waiting", state="WAITING_HUMAN", wait_reason="请登录")
    )
    asyncio.run(ctx.repo.create_task("z-done", "https://example.com", "p1"))
    asyncio.run(ctx.repo.update_task("z-done", state="DONE"))

    with TestClient(app, base_url="http://127.0.0.1"):
        pass  # 进入即触发 lifespan 启动清理

    states = {
        tid: asyncio.run(ctx.repo.get_task(tid)) for tid in
        ["z-queued", "z-running", "z-waiting", "z-done"]
    }
    for tid in ("z-queued", "z-running", "z-waiting"):
        row = states[tid]
        assert row is not None and row["state"] == "CANCELLED", (tid, row)
        assert "服务重启" in row["wait_reason"], row
    # 已完结状态不受影响
    assert states["z-done"]["state"] == "DONE"


def test_no_stale_tasks_startup_is_noop(ctx_factory: Any) -> None:
    ctx = ctx_factory(FakeRunner())
    app = create_app(ctx=ctx)
    with TestClient(app, base_url="http://127.0.0.1"):
        pass
    assert asyncio.run(ctx.repo.cancel_stale_active_tasks("再次清理")) == 0
