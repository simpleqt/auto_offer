"""ChatOpenAI 封装：实现 LLMClient 协议（docs/03 §4.1）。

- 对接任意 OpenAI 兼容端点（vLLM 等），透传 extra_body。
- complete_json：结构化输出 + Pydantic 校验，失败带错误信息重试（≤2 次）。
- 并发信号量（端点 max_concurrency）与 usage 统计。
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from typing import Any

import structlog
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from autooffer_core.errors import LLMError
from autooffer_core.llm.interfaces import (
    ChatMessage,
    LLMResponse,
    LLMUsage,
    ModelEndpoint,
)

log = structlog.get_logger(__name__)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)
_MAX_JSON_RETRIES = 2


def _to_langchain_messages(messages: list[ChatMessage]) -> list[tuple[str, Any]]:
    """转为 langchain 消息；带图片的消息用多模态 content 块。"""
    out: list[tuple[str, Any]] = []
    for m in messages:
        if m.images:
            blocks: list[dict[str, Any]] = [{"type": "text", "text": m.content}]
            for img in m.images:
                b64 = base64.b64encode(img).decode("ascii")
                blocks.append(
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                )
            out.append((m.role, blocks))
        else:
            out.append((m.role, m.content))
    return out


def extract_json_text(text: str) -> str:
    """从模型输出中提取 JSON 文本：优先 ```json 代码块，其次首个大括号配对段。"""
    m = _JSON_BLOCK_RE.search(text)
    if m:
        return m.group(1)
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


class ChatOpenAIClient:
    """基于 langchain_openai.ChatOpenAI 的 LLMClient 实现。"""

    def __init__(self, endpoint: ModelEndpoint) -> None:
        self.endpoint = endpoint
        self.supports_vision = bool(endpoint.supports_vision)
        self._sem = asyncio.Semaphore(max(1, endpoint.max_concurrency))
        self._chat = ChatOpenAI(
            model=endpoint.model,
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
            temperature=endpoint.temperature,
            max_completion_tokens=endpoint.max_tokens,
            timeout=endpoint.timeout_s,
            max_retries=1,
            extra_body=endpoint.extra_body or None,
        )
        self.total_usage = LLMUsage()

    def _record_usage(self, msg: BaseMessage, latency_ms: int) -> LLMUsage:
        meta = getattr(msg, "usage_metadata", None) or {}
        usage = LLMUsage(
            prompt_tokens=int(meta.get("input_tokens", 0)),
            completion_tokens=int(meta.get("output_tokens", 0)),
            total_tokens=int(meta.get("total_tokens", 0)),
            latency_ms=latency_ms,
        )
        self.total_usage = LLMUsage(
            prompt_tokens=self.total_usage.prompt_tokens + usage.prompt_tokens,
            completion_tokens=self.total_usage.completion_tokens + usage.completion_tokens,
            total_tokens=self.total_usage.total_tokens + usage.total_tokens,
            latency_ms=self.total_usage.latency_ms + latency_ms,
        )
        return usage

    async def _ainvoke_raw(self, lc_messages: list[tuple[str, Any]], **kwargs: Any) -> BaseMessage:
        """底层调用点（独立方法便于测试替换）。"""
        result: BaseMessage = await self._chat.ainvoke(lc_messages, **kwargs)
        return result

    async def _invoke(self, messages: list[ChatMessage], **kwargs: Any) -> LLMResponse:
        lc_messages = _to_langchain_messages(messages)
        started = time.monotonic()
        async with self._sem:
            try:
                msg = await self._ainvoke_raw(lc_messages, **kwargs)
            except Exception as exc:  # 网络/端点错误统一为 LLMError
                raise LLMError(f"LLM 调用失败: {exc}", retryable=True) from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        text = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
        usage = self._record_usage(msg, latency_ms)
        log.debug(
            "llm.complete",
            model=self.endpoint.model,
            latency_ms=latency_ms,
            tokens=usage.total_tokens,
        )
        return LLMResponse(text=text, usage=usage, model=self.endpoint.model)

    async def complete(self, messages: list[ChatMessage]) -> LLMResponse:
        return await self._invoke(messages)

    async def complete_json(
        self,
        messages: list[ChatMessage],
        schema: type[BaseModel],
    ) -> BaseModel:
        """结构化输出：请求 JSON、解析并 Pydantic 校验；失败带错误重试。"""
        work = list(messages)
        last_error = ""
        for attempt in range(_MAX_JSON_RETRIES + 1):
            resp = await self._invoke(
                work, response_format={"type": "json_object"}
            )
            raw = extract_json_text(resp.text)
            try:
                return schema.model_validate_json(raw)
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)[:800]
                log.warning(
                    "llm.json_invalid",
                    attempt=attempt,
                    schema=schema.__name__,
                    error=last_error[:200],
                )
                work = [
                    *messages,
                    ChatMessage(role="assistant", content=resp.text[:4000]),
                    ChatMessage(
                        role="user",
                        content=(
                            "你上一条回复不是合法的目标 JSON，校验错误如下：\n"
                            f"{last_error}\n"
                            "请只输出修正后的 JSON 对象，不要任何其他文字。"
                        ),
                    ),
                ]
        raise LLMError(
            f"结构化输出校验失败（{schema.__name__}，已重试 {_MAX_JSON_RETRIES} 次）: {last_error}",
            retryable=False,
        )
