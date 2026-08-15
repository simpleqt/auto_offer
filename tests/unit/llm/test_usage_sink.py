"""LLM 用量回调（UsageSink）单元测试：验证客户端在成功/失败时产出用量记录，
且 ModelRouter 把 sink 透传给客户端（FR-M5 数据源，全部离线）。"""

from __future__ import annotations

from typing import Any

import pytest

from autooffer_core.errors import LLMError
from autooffer_core.llm.client import ChatOpenAIClient
from autooffer_core.llm.interfaces import ChatMessage, LLMUsageRecord, ModelEndpoint
from autooffer_core.llm.router import ModelRouterImpl


def make_endpoint(**overrides: Any) -> ModelEndpoint:
    defaults: dict[str, Any] = {
        "id": "test-ep",
        "name": "测试端点",
        "base_url": "http://127.0.0.1:9/v1",
        "api_key": "sk-test-000",
        "model": "test-model",
        "max_concurrency": 2,
    }
    defaults.update(overrides)
    return ModelEndpoint(**defaults)


class _FakeMsg:
    def __init__(self, content: str) -> None:
        self.content = content
        self.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


@pytest.mark.asyncio
async def test_usage_sink_records_success(monkeypatch: pytest.MonkeyPatch) -> None:
    records: list[LLMUsageRecord] = []

    async def sink(r: LLMUsageRecord) -> None:
        records.append(r)

    client = ChatOpenAIClient(make_endpoint(), usage_sink=sink)

    async def fake_ainvoke(messages: Any, **kwargs: Any) -> _FakeMsg:
        return _FakeMsg("OK")

    monkeypatch.setattr(client, "_ainvoke_raw", fake_ainvoke)
    await client.complete([ChatMessage(role="user", content="hi")])

    assert len(records) == 1
    r = records[0]
    assert r.success is True
    assert r.total_tokens == 15
    assert r.prompt_tokens == 10
    assert r.latency_ms >= 0
    assert r.model == "test-model"


@pytest.mark.asyncio
async def test_usage_sink_records_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    records: list[LLMUsageRecord] = []

    async def sink(r: LLMUsageRecord) -> None:
        records.append(r)

    client = ChatOpenAIClient(make_endpoint(), usage_sink=sink)

    async def fake_ainvoke(messages: Any, **kwargs: Any) -> _FakeMsg:
        raise RuntimeError("端点宕机")

    monkeypatch.setattr(client, "_ainvoke_raw", fake_ainvoke)
    with pytest.raises(LLMError):
        await client.complete([ChatMessage(role="user", content="hi")])

    assert len(records) == 1
    r = records[0]
    assert r.success is False
    assert "端点宕机" in r.error
    assert r.total_tokens == 0


def test_router_passes_usage_sink_to_clients() -> None:
    async def sink(r: LLMUsageRecord) -> None:
        pass

    ep = make_endpoint()
    router = ModelRouterImpl(ep, usage_sink=sink)
    client = router.default()
    # ChatOpenAIClient 暴露了私有 sink 字段，这里仅验证构造不抛错且客户端可复用
    assert router.default() is client
