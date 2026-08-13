"""LLM 接入契约（docs/03 §4）。

- LLMClient：统一的对话/结构化输出/多模态调用接口。
- ModelRouter：按智能体角色路由到不同模型端点。
- ModelEndpoint：用户可配置的 OpenAI 兼容端点（含视觉能力探测缓存）。

实现仅依赖 OpenAI 兼容 Chat Completions 接口（NFR-2）。
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, SecretStr

Role = Literal["planner", "actor", "validator", "profile_parser", "writer"]

DEFAULT_ROLE: Role = "actor"


class ModelEndpoint(BaseModel):
    """一个可由用户在应用端配置的模型端点（FR-M1）。"""

    id: str
    name: str
    base_url: str
    api_key: SecretStr
    model: str
    temperature: float = 0.1
    max_tokens: int = 4096
    timeout_s: int = 600
    max_concurrency: int = 4
    extra_body: dict[str, Any] = {}
    """如 {"chat_template_kwargs": {"enable_thinking": false}}。"""

    supports_vision: bool | None = None
    """视觉能力探测结果缓存（None=未探测），见 probe_endpoint。"""


class ChatMessage(BaseModel):
    """统一消息模型；content 为文本，images 为 base64（不含 data: 前缀）。"""

    role: Literal["system", "user", "assistant"]
    content: str
    images: list[bytes] = []
    """多模态输入图片（PNG/JPEG 字节），视觉模型可用时使用。"""


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0


class LLMResponse(BaseModel):
    text: str
    usage: LLMUsage = LLMUsage()
    model: str = ""


@runtime_checkable
class LLMClient(Protocol):
    """统一 LLM 调用接口。

    - complete：自由文本对话。
    - complete_json：结构化输出。实现需做 Pydantic 校验，
      校验失败时携带错误信息自动重试（≤2 次），仍失败抛 LLMError。
    """

    supports_vision: bool

    async def complete(self, messages: list[ChatMessage]) -> LLMResponse:
        ...

    async def complete_json(
        self,
        messages: list[ChatMessage],
        schema: type[BaseModel],
    ) -> BaseModel:
        ...


@runtime_checkable
class ModelRouter(Protocol):
    """按角色路由模型端点（FR-M3）。

    未为某角色显式配置端点时，回落到默认端点。
    """

    def get(self, role: Role) -> LLMClient:
        ...

    def default(self) -> LLMClient:
        ...


class ProbeResult(BaseModel):
    """模型端点能力探测结果（FR-M2）。"""

    reachable: bool
    """是否可连通（/v1/models + 最小对话）。"""

    supports_vision: bool | None = None
    """是否支持图像输入（None=未能判定）。"""

    available_models: list[str] = []
    latency_ms: int = 0
    error: str | None = None
