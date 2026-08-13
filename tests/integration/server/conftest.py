"""服务层集成测试夹具：临时数据目录 + 假执行体（不连模型/浏览器）。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from autooffer_core.report import FieldRecord, FillReport
from autooffer_server.config import ServerConfig
from autooffer_server.context import AppContext
from autooffer_server.main import create_app
from autooffer_server.services.keystore import KeyStore


class MemoryKeyStore(KeyStore):
    """内存密钥库：避免测试污染真实系统凭据管理器。"""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def store(self, key_id: str, secret: str) -> None:
        self._data[key_id] = secret

    async def retrieve(self, key_id: str) -> str | None:
        return self._data.get(key_id)

    async def delete(self, key_id: str) -> None:
        self._data.pop(key_id, None)


class FakeRunner:
    """假执行体：产出若干事件后返回填写报告。

    pause_reason 非空时先触发一次人工介入门（用于测试 WAITING_HUMAN → resume）。
    """

    def __init__(self, *, pause_reason: str | None = None, fail: bool = False) -> None:
        self.pause_reason = pause_reason
        self.fail = fail
        self.started = asyncio.Event()

    async def run(
        self, *, task_id: str, url: str, profile_id: str, on_event: Any, human_gate: Any
    ) -> dict[str, Any]:
        self.started.set()
        on_event({"kind": "step", "agent": "planner", "summary": "拆分区块"})
        if self.fail:
            raise RuntimeError("模拟执行失败")
        if self.pause_reason:
            await human_gate(self.pause_reason)
            on_event({"kind": "step", "agent": "runner", "summary": "人工处理完成，继续"})
        on_event({"kind": "step", "agent": "actor", "summary": "填写姓名"})
        report = FillReport(
            task_id=task_id,
            url=url,
            page_title="示例公司 - 招聘",
            profile_id=profile_id,
            fields=[
                FieldRecord(label="姓名", status="filled", value="张三"),
                FieldRecord(label="期望薪资", status="pending_confirm"),
            ],
        )
        on_event({"kind": "report", "agent": "runner", "summary": "报告生成"})
        return report.model_dump()


@pytest.fixture
def ctx_factory(tmp_path: Path) -> Any:
    def make(runner: Any) -> AppContext:
        config = ServerConfig.create(tmp_path / "data", headless=True)
        return AppContext(config, runner=runner, keystore=MemoryKeyStore())

    return make


@pytest.fixture
def fake_runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def client(ctx_factory: Any, fake_runner: FakeRunner) -> Iterator[TestClient]:
    app = create_app(ctx=ctx_factory(fake_runner))
    with TestClient(app) as c:
        yield c


def sample_profile_payload() -> dict[str, Any]:
    from autooffer_core.testing import build_sample_profile

    return build_sample_profile().model_dump(mode="json")
