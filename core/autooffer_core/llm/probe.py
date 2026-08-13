"""模型端点能力探测（docs/03 §4.2，FR-M2）。

三步：/models 连通性 → 最小对话 → 1px 图片探测视觉能力。
"""

from __future__ import annotations

import time

import httpx
import structlog

from autooffer_core.llm.interfaces import ModelEndpoint, ProbeResult

log = structlog.get_logger(__name__)

# 1x1 红色 PNG
_TEST_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
    "AAAABJRU5ErkJggg=="
)


async def probe_endpoint(ep: ModelEndpoint, *, timeout_s: float = 30.0) -> ProbeResult:
    headers = {"Authorization": f"Bearer {ep.api_key.get_secret_value()}"}
    base = ep.base_url.rstrip("/")
    started = time.monotonic()
    available: list[str] = []

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        # 1) /models 连通性
        try:
            r = await client.get(f"{base}/models", headers=headers)
            r.raise_for_status()
            data = r.json()
            available = [str(m.get("id", "")) for m in data.get("data", [])]
        except (httpx.HTTPError, ValueError) as exc:
            return ProbeResult(
                reachable=False,
                error=f"/models 请求失败: {exc}",
                latency_ms=int((time.monotonic() - started) * 1000),
            )

        # 2) 最小对话
        chat_url = f"{base}/chat/completions"
        try:
            r = await client.post(
                chat_url,
                headers=headers,
                json={
                    "model": ep.model,
                    "messages": [{"role": "user", "content": "回复：OK"}],
                    "max_tokens": 8,
                    # OpenAI SDK 的 extra_body 字段在原始 HTTP 请求中直接平铺进 body
                    **(ep.extra_body or {}),
                },
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            return ProbeResult(
                reachable=False,
                available_models=available,
                error=f"最小对话失败: {exc}",
                latency_ms=int((time.monotonic() - started) * 1000),
            )

        # 3) 视觉能力：发送 1px 图片
        supports_vision: bool | None = None
        try:
            r = await client.post(
                chat_url,
                headers=headers,
                json={
                    "model": ep.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "这张图是什么颜色？一个词回答。"},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{_TEST_PNG_B64}"
                                    },
                                },
                            ],
                        }
                    ],
                    "max_tokens": 16,
                },
            )
            supports_vision = r.status_code == 200
        except httpx.HTTPError:
            supports_vision = False

    latency_ms = int((time.monotonic() - started) * 1000)
    log.info(
        "llm.probe_done",
        endpoint=ep.id,
        reachable=True,
        supports_vision=supports_vision,
        latency_ms=latency_ms,
    )
    return ProbeResult(
        reachable=True,
        supports_vision=supports_vision,
        available_models=available,
        latency_ms=latency_ms,
    )
