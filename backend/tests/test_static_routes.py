"""测试——SPA static fallback 路由。"""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from httpx import ASGITransport, AsyncClient

from backend.config import get_settings
from backend.server.library_routes import library_router
from backend.server.routes import router as api_router
from backend.server.static_routes import router as static_router

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def static_app(tmp_path: Path) -> AsyncGenerator[tuple[FastAPI, Path], None]:
    """建一个带 StaticFiles + static_router 的 app，返回 (app, static_dir)。

    挂载顺序模拟生产 main.py：
    1. /api/* 路由先注册
    2. /assets StaticFiles mount
    3. static_router catch-all 兜底
    """
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    assets_dir = static_dir / "assets"
    assets_dir.mkdir()
    # 假 index.html
    (static_dir / "index.html").write_text("<!DOCTYPE html><title>Lyra</title>", encoding="utf-8")
    # 假静态资产
    (assets_dir / "app.js").write_text("console.log('app');", encoding="utf-8")

    # 临时设 LYRA_STATIC_DIR 让 get_settings() 读到
    import os

    old = os.environ.get("LYRA_STATIC_DIR")
    os.environ["LYRA_STATIC_DIR"] = str(static_dir)
    # 清掉可能的 settings 缓存（get_settings 每次新建，无缓存，但保险）
    try:
        app = FastAPI()
        app.include_router(api_router, prefix="/api")
        app.include_router(library_router, prefix="/api")
        # StaticFiles mount /assets（必须在 catch-all 路由注册前）
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
        # catch-all 最后注册
        app.include_router(static_router)

        yield app, static_dir
    finally:
        if old is None:
            os.environ.pop("LYRA_STATIC_DIR", None)
        else:
            os.environ["LYRA_STATIC_DIR"] = old


@pytest.fixture
async def no_static_app(tmp_path: Path) -> AsyncGenerator[FastAPI, None]:
    """static_dir 未配置（本机开发态）的 app。"""
    import os

    old = os.environ.get("LYRA_STATIC_DIR")
    os.environ.pop("LYRA_STATIC_DIR", None)
    try:
        app = FastAPI()
        app.include_router(api_router, prefix="/api")
        # static_router 仍注册，但 spa_fallback 应返 404（static_dir=None）
        app.include_router(static_router)
        yield app
    finally:
        if old is not None:
            os.environ["LYRA_STATIC_DIR"] = old


async def _client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


async def test_spa_fallback_returns_index_html(static_app: tuple[FastAPI, Path]) -> None:
    """非 /api 路径 → 返回 index.html（text/html）。"""
    app, _ = static_app
    async with await _client(app) as c:
        resp = await c.get("/track/123")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "<title>Lyra</title>" in resp.text


async def test_spa_fallback_nested_path(static_app: tuple[FastAPI, Path]) -> None:
    """深层嵌套路径 → 仍返回 index.html（vue-router history 模式）。"""
    app, _ = static_app
    async with await _client(app) as c:
        resp = await c.get("/track/456/lyrics-editor")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


async def test_spa_fallback_root_path(static_app: tuple[FastAPI, Path]) -> None:
    """根路径 / → 返回 index.html。"""
    app, _ = static_app
    async with await _client(app) as c:
        resp = await c.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


async def test_api_routes_not_intercepted(static_app: tuple[FastAPI, Path]) -> None:
    """/api/* 不被 catch-all 拦截，正常走 API 路由。"""
    app, _ = static_app
    async with await _client(app) as c:
        # /api/library 会因 store 未初始化返 503，但不应该是 index.html
        resp = await c.get("/api/library")
        assert resp.status_code == 503
        assert resp.headers.get("content-type", "").startswith("application/json")


async def test_api_health_not_intercepted(static_app: tuple[FastAPI, Path]) -> None:
    """/api/health 不被 catch-all 拦截。"""
    app, _ = static_app
    async with await _client(app) as c:
        resp = await c.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"


async def test_assets_served_by_staticfiles(static_app: tuple[FastAPI, Path]) -> None:
    """/assets/* 由 StaticFiles mount 处理，不走到 catch-all。"""
    app, _ = static_app
    async with await _client(app) as c:
        resp = await c.get("/assets/app.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers.get("content-type", "") or "text/plain" in resp.headers.get("content-type", "")


async def test_static_dir_not_configured_returns_404(no_static_app: FastAPI) -> None:
    """static_dir=None（开发态）时 catch-all 返 JSON 404，不崩。"""
    async with await _client(no_static_app) as c:
        resp = await c.get("/track/123")
        assert resp.status_code == 404
        body = resp.json()
        assert "not configured" in body["detail"].lower()
