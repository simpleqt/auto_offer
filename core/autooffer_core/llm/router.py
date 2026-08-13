"""模型角色路由（docs/03 §4.1，FR-M3）。

角色（planner/actor/validator/profile_parser/writer）→ 模型端点；
未显式配置的角色回落默认端点。客户端按端点惰性创建并复用。
"""

from __future__ import annotations

import structlog

from autooffer_core.llm.client import ChatOpenAIClient
from autooffer_core.llm.interfaces import LLMClient, ModelEndpoint, Role

log = structlog.get_logger(__name__)


class ModelRouterImpl:
    """默认端点 + 角色覆写的路由实现。"""

    def __init__(
        self,
        default_endpoint: ModelEndpoint,
        role_endpoints: dict[Role, ModelEndpoint] | None = None,
    ) -> None:
        self._default_ep = default_endpoint
        self._role_eps: dict[Role, ModelEndpoint] = dict(role_endpoints or {})
        self._clients: dict[str, LLMClient] = {}

    def _client_for(self, ep: ModelEndpoint) -> LLMClient:
        client = self._clients.get(ep.id)
        if client is None:
            client = ChatOpenAIClient(ep)
            self._clients[ep.id] = client
            log.info("llm.client_created", endpoint=ep.id, model=ep.model)
        return client

    def get(self, role: Role) -> LLMClient:
        ep = self._role_eps.get(role, self._default_ep)
        return self._client_for(ep)

    def default(self) -> LLMClient:
        return self._client_for(self._default_ep)
