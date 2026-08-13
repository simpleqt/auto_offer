"""应用上下文：把配置、存储、密钥库、调度器装配在一起。

路由与 WS 只依赖本上下文，测试可替换 runner / keystore 实现。
"""

from __future__ import annotations

from typing import Any

import structlog
from pydantic import SecretStr

from autooffer_core.llm.interfaces import ModelEndpoint, Role
from autooffer_server.config import ServerConfig
from autooffer_server.db.repo import Repo
from autooffer_server.services.events import EventBus
from autooffer_server.services.keystore import KeyStore
from autooffer_server.services.task_scheduler import TaskRunner, TaskScheduler

log = structlog.get_logger(__name__)


class AppContext:
    def __init__(
        self,
        config: ServerConfig,
        *,
        runner: TaskRunner | None = None,
        keystore: KeyStore | None = None,
    ) -> None:
        config.ensure_dirs()
        self.config = config
        self.repo = Repo(config.db_path)
        self.bus = EventBus()
        self.keystore = keystore or KeyStore(config.data_dir / "keys.json")
        if runner is None:
            from autooffer_server.services.agent_runner import AgentTaskRunner

            runner = AgentTaskRunner(self)
        self.scheduler = TaskScheduler(
            self.repo, self.bus, runner, max_concurrent=config.max_concurrent_tasks
        )

    async def build_endpoint(self, endpoint_id: str | None = None) -> ModelEndpoint:
        """从库中取端点 + 密钥库取 key → ModelEndpoint。"""
        row = (
            await self.repo.get_endpoint(endpoint_id)
            if endpoint_id
            else await self.repo.get_default_endpoint()
        )
        if row is None:
            raise LookupError(f"模型端点不存在: {endpoint_id or '(默认)'}")
        api_key = await self.keystore.retrieve(row["id"])
        if not api_key:
            raise LookupError(f"端点未配置 api_key: {row['id']}")
        return ModelEndpoint(
            id=row["id"],
            name=row["name"],
            base_url=row["base_url"],
            api_key=SecretStr(api_key),
            model=row["model"],
            temperature=row["temperature"],
            max_tokens=row["max_tokens"],
            timeout_s=row["timeout_s"],
            max_concurrency=row["max_concurrency"],
            extra_body=row["extra_body"],
            supports_vision=row["supports_vision"],
        )

    async def build_llm(self, role: Role = "actor") -> Any:
        """按角色路由取 LLM 客户端（未配置角色时用默认端点）。"""
        from autooffer_core.llm.client import ChatOpenAIClient

        routing = await self.repo.get_routing()
        ep = await self.build_endpoint(routing.get(role))
        return ChatOpenAIClient(ep)

    async def build_router(self) -> Any:
        """构造 ModelRouter（角色 → 端点覆写）。"""
        from autooffer_core.llm.router import ModelRouterImpl

        default_ep = await self.build_endpoint(None)
        routing = await self.repo.get_routing()
        overrides: dict[Role, ModelEndpoint] = {}
        for role, endpoint_id in routing.items():
            if endpoint_id and endpoint_id != default_ep.id:
                try:
                    overrides[role] = await self.build_endpoint(endpoint_id)  # type: ignore[index]
                except LookupError:
                    log.warning("context.routing_endpoint_missing", role=role, id=endpoint_id)
        return ModelRouterImpl(default_ep, overrides)

    async def shutdown(self) -> None:
        await self.scheduler.shutdown()
