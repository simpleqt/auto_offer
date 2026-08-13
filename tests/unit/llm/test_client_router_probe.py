"""LLM 接入层单元测试（全部离线：monkeypatch / 假 HTTP 传输）。"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from autooffer_core.errors import LLMError
from autooffer_core.llm.client import ChatOpenAIClient, extract_json_text
from autooffer_core.llm.interfaces import ChatMessage, ModelEndpoint
from autooffer_core.llm.probe import probe_endpoint
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


# ---------- extract_json_text ----------

def test_extract_json_from_code_block() -> None:
    text = '前言\n```json\n{"a": 1}\n```\n后记'
    assert extract_json_text(text) == '{"a": 1}'


def test_extract_json_by_brace_matching() -> None:
    text = '好的，结果是 {"a": {"b": 2}} 供参考'
    assert extract_json_text(text) == '{"a": {"b": 2}}'


def test_extract_json_no_brace_returns_original() -> None:
    assert extract_json_text("没有 JSON") == "没有 JSON"


# ---------- ChatOpenAIClient.complete_json（monkeypatch ainvoke）----------

class _Out(BaseModel):
    name: str
    age: int


class _FakeMsg:
    def __init__(self, content: str) -> None:
        self.content = content
        self.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


@pytest.mark.asyncio
async def test_complete_json_retry_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ChatOpenAIClient(make_endpoint())
    responses = ['{"name": "张三"}', '{"name": "张三", "age": 24}']  # 第一次缺字段
    calls: list[list[Any]] = []

    async def fake_ainvoke(messages: Any, **kwargs: Any) -> _FakeMsg:
        calls.append(messages)
        return _FakeMsg(responses[len(calls) - 1])

    monkeypatch.setattr(client, "_ainvoke_raw", fake_ainvoke)
    result = await client.complete_json([ChatMessage(role="user", content="给我")], _Out)
    assert isinstance(result, _Out)
    assert result.age == 24
    assert len(calls) == 2
    # 重试请求包含校验错误反馈
    retry_texts = [m for m in calls[1] if isinstance(m, tuple)]
    assert any("校验错误" in str(m) or "JSON" in str(m) for m in retry_texts)


@pytest.mark.asyncio
async def test_complete_json_exhausted_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ChatOpenAIClient(make_endpoint())

    async def fake_ainvoke(messages: Any, **kwargs: Any) -> _FakeMsg:
        return _FakeMsg("完全不是 JSON")

    monkeypatch.setattr(client, "_ainvoke_raw", fake_ainvoke)
    with pytest.raises(LLMError):
        await client.complete_json([ChatMessage(role="user", content="x")], _Out)


@pytest.mark.asyncio
async def test_complete_records_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ChatOpenAIClient(make_endpoint())

    async def fake_ainvoke(messages: Any, **kwargs: Any) -> _FakeMsg:
        return _FakeMsg("OK")

    monkeypatch.setattr(client, "_ainvoke_raw", fake_ainvoke)
    resp = await client.complete([ChatMessage(role="user", content="hi")])
    assert resp.text == "OK"
    assert resp.usage.total_tokens == 15
    assert client.total_usage.total_tokens == 15


# ---------- 路由 ----------

def test_router_role_override_and_default() -> None:
    default_ep = make_endpoint(id="default-ep")
    validator_ep = make_endpoint(id="small-ep", model="small-model")
    router = ModelRouterImpl(default_ep, {"validator": validator_ep})

    assert router.get("actor") is router.default()
    assert router.get("validator") is not router.default()
    # 同端点客户端复用
    assert router.get("validator") is router.get("validator")


# ---------- 探测（httpx MockTransport 注入）----------

@pytest.mark.asyncio
async def test_probe_reachable_with_vision(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "test-model"}]})
        body = request.content.decode("utf-8")
        if "image_url" in body:
            return httpx.Response(200, json={"choices": []})
        return httpx.Response(200, json={"choices": []})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def patched(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(**kwargs)

    monkeypatch.setattr("autooffer_core.llm.probe.httpx.AsyncClient", patched)
    result = await probe_endpoint(make_endpoint())
    assert result.reachable is True
    assert result.supports_vision is True
    assert result.available_models == ["test-model"]


@pytest.mark.asyncio
async def test_probe_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def patched(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(**kwargs)

    monkeypatch.setattr("autooffer_core.llm.probe.httpx.AsyncClient", patched)
    result = await probe_endpoint(make_endpoint())
    assert result.reachable is False
    assert result.error is not None
