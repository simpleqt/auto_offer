"""本地服务应用工厂（docs/03 §5.5）。

仅绑定 127.0.0.1（FR-D3）；CORS 只放行本机开发前端。
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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
    config: ServerConfig | None = None,
    *,
    ctx: AppContext | None = None,
    frontend_dir: Path | str | None = None,
) -> FastAPI:
    """构造应用。传入 ctx 可注入测试替身（假 runner / 临时数据目录）。

    frontend_dir 显式指定前端构建产物目录（测试用）；缺省时按仓库/打包布局自动探测。
    """
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
    _mount_frontend(app, frontend_dir)
    return app


def _frontend_dist() -> Path | None:
    """定位前端构建产物目录（开发仓库内 frontend/dist，或打包后与主程序同目录）。"""
    candidates = [
        # 仓库开发布局：server/autooffer_server/main.py → 仓库根/frontend/dist
        Path(__file__).resolve().parents[2] / "frontend" / "dist",
        # 打包（onedir）布局：可执行文件同级的 frontend/dist
        Path(__file__).resolve().parent / "frontend" / "dist",
    ]
    for cand in candidates:
        if (cand / "index.html").exists():
            return cand
    return None


def _mount_frontend(app: FastAPI, dist_dir: Path | str | None = None) -> None:
    """有前端构建产物时挂载 SPA；无则仅提供 API（开发模式由 Vite 独立服务）。"""
    dist = Path(dist_dir) if dist_dir is not None else _frontend_dist()
    if dist is None or not (dist / "index.html").exists():
        log.info("server.frontend_missing", hint="开发模式请运行 `cd frontend && npm run dev`")
        return

    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        """SPA 回退：非 API 路径一律返回 index.html，交给前端路由。"""
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")

    log.info("server.frontend_mounted", dist=str(dist))


def run(**kwargs: Any) -> None:
    """启动服务（供 CLI `serve` 与桌面启动器调用）。"""
    import uvicorn

    config = ServerConfig.create(**kwargs)
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")
