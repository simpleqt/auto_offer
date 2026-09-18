"""本地服务应用工厂（docs/03 §5.5）。

仅绑定 127.0.0.1（FR-D3）；CORS 只放行本机开发前端。
"""

from __future__ import annotations

import contextlib
import sys
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

# 允许的 Host（本机回环 + Starlette TestClient）：防 DNS rebinding——
# 攻击者域名解析到 127.0.0.1 后，浏览器视为同源绕过 SOP 直读本地服务
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}

# 允许的 Origin（变更类请求与 WebSocket）：本机回环（桌面 UI 同源 /
# Vite 开发代理）与浏览器插件。恶意网页对本地服务发起跨站 POST
# （resume/cancel/multipart 上传等简单请求，无需 CORS 预检）时浏览器
# 必带真实 Origin 且不可伪造——据此拒绝。本机进程（curl 等）不发送
# Origin，不受影响。`null`（沙箱 iframe 可伪造）一律拒绝。
_ALLOWED_ORIGIN_PREFIXES = ("chrome-extension://", "moz-extension://")
_ALLOWED_ORIGIN_EXACT = set(_LOCAL_ORIGINS)


def _origin_allowed(origin: str) -> bool:
    o = origin.strip().lower().rstrip("/")
    if not o or o == "null":
        return False
    if o in _ALLOWED_ORIGIN_EXACT:
        return True
    if o.startswith(_ALLOWED_ORIGIN_PREFIXES):
        return True
    try:
        from urllib.parse import urlparse

        host = urlparse(o).hostname or ""
        return host in ("127.0.0.1", "localhost", "::1", "[::1]")
    except ValueError:
        return False


def _host_allowed(host: str) -> bool:
    if not host:
        return False
    h = host.strip().lower()
    # 剥端口（IPv6 形如 [::1]:8765）
    hostpart = (h.split("]")[0] + "]") if h.startswith("[") else h.split(":")[0]
    return hostpart in _ALLOWED_HOSTS


_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _header(scope: Any, name: bytes) -> str:
    return next(
        (v.decode("latin-1") for k, v in scope.get("headers", []) if k == name),
        "",
    )


class _HostGuardMiddleware:
    """本机回环防线：Host 与 Origin 双校验（DNS rebinding / 跨站写防御）。

    - Host 头不在回环名单 → 拒绝（HTTP 403；WS 拒绝握手）。
    - 变更类请求（POST/PUT/PATCH/DELETE）与 WebSocket 携带恶意 Origin
      → 拒绝：浏览器对跨站简单请求必带真实 Origin 且不可伪造，恶意网页
      无法再触发 resume/cancel/上传等副作用。本机进程不发 Origin，不受影响。
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            if not _host_allowed(_header(scope, b"host")):
                await self._reject(scope, receive, send)
                return
            origin = _header(scope, b"origin")
            needs_origin_check = scope["type"] == "websocket" or (
                scope.get("method") in _MUTATING_METHODS
            )
            if origin and needs_origin_check and not _origin_allowed(origin):
                await self._reject(scope, receive, send)
                return
        await self.app(scope, receive, send)

    async def _reject(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            from starlette.responses import JSONResponse

            resp = JSONResponse({"detail": "invalid Host/Origin header"}, status_code=403)
            await resp(scope, receive, send)
        else:
            # 握手前关闭：uvicorn 对未 accept 的 close 以 403 拒绝升级
            await send({"type": "websocket.close", "code": 1008})


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
        # 上次进程遗留的活跃态任务是僵尸（队列/gate 在内存里已丢失），
        # 启动即清理，避免任务列表永久悬挂
        await context.recover_stale_tasks()
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
    app.add_middleware(_HostGuardMiddleware)
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
    # PyInstaller 冻结态：--add-data 的 frontend/dist 解包到 _MEIPASS 下
    # （PyInstaller 6 onedir 在 <安装目录>/_internal/frontend/dist）
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.insert(0, Path(meipass) / "frontend" / "dist")
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
        candidate = (dist / full_path).resolve()
        # 路径规范化：编码 ../ 的穿越路径不得逃出 dist 目录
        # （is_relative_to 分隔符无关；startswith("dist/") 在 Windows 反斜杠下恒 False）
        if full_path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")

    log.info("server.frontend_mounted", dist=str(dist))


def run(**kwargs: Any) -> None:
    """启动服务（供 CLI `serve` 与桌面启动器调用）。"""
    import uvicorn

    config = ServerConfig.create(**kwargs)
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")
