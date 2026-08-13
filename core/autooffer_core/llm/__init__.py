"""LLM 接入：客户端、角色路由、能力探测。"""

from autooffer_core.llm.client import ChatOpenAIClient
from autooffer_core.llm.interfaces import (
    ChatMessage,
    LLMClient,
    LLMResponse,
    LLMUsage,
    ModelEndpoint,
    ModelRouter,
    ProbeResult,
    Role,
)
from autooffer_core.llm.probe import probe_endpoint
from autooffer_core.llm.router import ModelRouterImpl

__all__ = [
    "ChatMessage",
    "ChatOpenAIClient",
    "LLMClient",
    "LLMResponse",
    "LLMUsage",
    "ModelEndpoint",
    "ModelRouter",
    "ModelRouterImpl",
    "ProbeResult",
    "Role",
    "probe_endpoint",
]
