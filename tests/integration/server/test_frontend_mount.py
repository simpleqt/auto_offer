"""前端静态挂载（SPA 回退）集成测试：验证 index.html 回退、assets 服务、
API 路径不被遮蔽、无产物时优雅降级（离线，不依赖真实 frontend/dist）。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from tests.integration.server.conftest import MemoryKeyStore

from autooffer_server.config import ServerConfig
from autooffer_server.context import AppContext
from autooffer_server.main import create_app


def _make_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><body>APP</body></html>", encoding="utf-8"
    )
    (assets / "app.js").write_text("console.log('hi')", encoding="utf-8")
    return dist


def test_spa_index_and_fallback(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    with TestClient(create_app(frontend_dir=dist)) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "APP" in r.text

        # 前端路由（非文件路径）回退到 index.html
        r2 = c.get("/profiles")
        assert r2.status_code == 200
        assert "APP" in r2.text


def test_spa_assets_served(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    with TestClient(create_app(frontend_dir=dist)) as c:
        r = c.get("/assets/app.js")
        assert r.status_code == 200
        assert r.text == "console.log('hi')"


def test_api_and_docs_not_shadowed(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    with TestClient(create_app(frontend_dir=dist)) as c:
        assert c.get("/api/v1/system/health").status_code == 200
        assert c.get("/docs").status_code == 200
        assert c.get("/openapi.json").status_code == 200


def test_no_frontend_dir_degrades_to_api_only(tmp_path: Path) -> None:
    """无 frontend/dist 时仅提供 API，根路径返回 404（而非 500）。

    显式传入一个不存在的目录，避免 create_app 自动探测到仓库内真实的 frontend/dist。
    """
    config = ServerConfig.create(tmp_path / "data", headless=True)
    ctx = AppContext(config, keystore=MemoryKeyStore())
    with TestClient(create_app(ctx=ctx, frontend_dir=tmp_path / "does-not-exist")) as c:
        assert c.get("/api/v1/system/health").status_code == 200
        assert c.get("/").status_code == 404
