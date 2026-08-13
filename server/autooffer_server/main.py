"""本地服务应用工厂（docs/03 §5.5）。

仅绑定 127.0.0.1（FR-D3）；CORS 只放行本机开发前端。
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from autooffer_core import __version__
from autooffer_server.api.routes import router
from autooffer_server.config import ServerConfig
from autooffer_server.context import AppContext
from autooffer_server.ws.tasks_ws import ws_router

log = structlog.get_logger(__name__)

# 本机开发前端（Vite 默认端口）
_LOCAL_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]


def create_app(
    config: ServerConfig | None = None, *, ctx: AppContext | None = None
) -> FastAPI:
    """构造应用。传入 ctx 可注入测试替身（假 runner / 临时数据目录）。"""
    context = ctx or AppContext(config or ServerConfig.create())

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info(
            "server.started",
            version=__version__,
            data_dir=str(context.config.data_dir),
            host=context.config.host,
        )
        yield
        await context.shutdown()
        log.info("server.stopped")

    app = FastAPI(
        title="AutoOffer 本地服务",
        version=__version__,
        description="简历自动填写智能体的本机服务（仅监听 127.0.0.1）",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_LOCAL_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.ctx = context
    app.include_router(router)
    app.include_router(ws_router)
    return app


def run(**kwargs: Any) -> None:
    """启动服务（供 CLI `serve` 与桌面启动器调用）。"""
    import uvicorn

    config = ServerConfig.create(**kwargs)
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")
