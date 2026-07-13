"""测试——settings 路由 + credits_base_url 行为。"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.index.store import IndexStore, set_store
from backend.meta.credits import _APPLE_DIRECT_URL
from backend.server.library_routes import library_router
from backend.server.routes import router as api_router
from backend.server.settings_routes import settings_router

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def app() -> FastAPI:
    """带 settings_router 的最小 app（不含 lifespan，store 手动注入）。"""
    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    app.include_router(library_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    return app


@pytest.fixture
async def store(tmp_path: object) -> AsyncGenerator[IndexStore, None]:
    """已初始化 schema 的 IndexStore，teardown 清空单例。"""
    db_path = tmp_path / "test.db"  # type: ignore[operator]
    store = IndexStore(db_path)  # type: ignore[arg-type]
    await store.init_schema()
    set_store(store)
    yield store
    set_store(None)


@pytest.fixture
async def client(app: FastAPI, store: IndexStore) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/settings
# ---------------------------------------------------------------------------


async def test_get_settings_empty_first_run(client: AsyncClient) -> None:
    """首次启动（app_settings 无行）返 credits_base_url="" + updated_at=0。"""
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["credits_base_url"] == ""
    assert body["updated_at"] == 0


async def test_get_settings_store_unavailable(app: FastAPI) -> None:
    """store=None 时 GET 返空值默认（不 503，降级）。"""
    set_store(None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["credits_base_url"] == ""
        assert body["updated_at"] == 0


# ---------------------------------------------------------------------------
# PUT /api/settings
# ---------------------------------------------------------------------------


async def test_update_settings_persists(client: AsyncClient) -> None:
    """PUT 后再 GET 读回写入值。"""
    resp = await client.put("/api/settings", json={"credits_base_url": "https://proxy.example.com"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["credits_base_url"] == "https://proxy.example.com"
    assert body["updated_at"] > 0

    # GET 读回
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["credits_base_url"] == "https://proxy.example.com"


async def test_update_settings_strips_whitespace(client: AsyncClient) -> None:
    """PUT 首尾空白被 strip。"""
    resp = await client.put(
        "/api/settings", json={"credits_base_url": "  https://x.example.com  "}
    )
    assert resp.status_code == 200
    assert resp.json()["credits_base_url"] == "https://x.example.com"


async def test_update_settings_empty_string(client: AsyncClient) -> None:
    """空字符串=直连 music.apple.com（存空串）。"""
    resp = await client.put("/api/settings", json={"credits_base_url": ""})
    assert resp.status_code == 200
    assert resp.json()["credits_base_url"] == ""


async def test_update_settings_store_unavailable(app: FastAPI) -> None:
    """store=None 时 PUT 返 503（写操作不能降级）。"""
    set_store(None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.put("/api/settings", json={"credits_base_url": "https://x.com"})
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# _resolve_base_url_from_store 行为（credits.py 集成）
# ---------------------------------------------------------------------------


async def test_resolve_base_url_returns_store_value(store: IndexStore) -> None:
    """app_settings 有值时 _resolve_base_url_from_store 返回该值。"""
    from backend.meta.credits import _resolve_base_url_from_store

    await store.set_app_settings(credits_base_url="https://my-proxy.workers.dev")
    result = await _resolve_base_url_from_store()
    assert result == "https://my-proxy.workers.dev"


async def test_resolve_base_url_empty_returns_direct(store: IndexStore) -> None:
    """credits_base_url="" 时直连 music.apple.com。"""
    from backend.meta.credits import _resolve_base_url_from_store

    await store.set_app_settings(credits_base_url="")
    result = await _resolve_base_url_from_store()
    assert result == _APPLE_DIRECT_URL


async def test_resolve_base_url_first_run_returns_direct(store: IndexStore) -> None:
    """首次启动（app_settings 无行）直连。"""
    from backend.meta.credits import _resolve_base_url_from_store

    result = await _resolve_base_url_from_store()
    assert result == _APPLE_DIRECT_URL


async def test_resolve_base_url_store_unavailable_returns_direct() -> None:
    """store=None 时降级直连（不抛异常）。"""
    from backend.meta.credits import _resolve_base_url_from_store

    set_store(None)
    result = await _resolve_base_url_from_store()
    assert result == _APPLE_DIRECT_URL


# ---------------------------------------------------------------------------
# fetch_credits 集成：确认 base_url 参数注入仍有效（测试 seam 不破坏）
# ---------------------------------------------------------------------------


async def test_fetch_credits_uses_injected_base_url() -> None:
    """base_url 参数注入时 fetch_credits 用它（不查 DB）。"""
    from backend.meta.credits import fetch_credits

    mock_client = MagicMock()
    mock_client.get = AsyncMock()
    # 让第一次请求就返回哨兵（永久无 credits），快速终止 fallback 链
    mock_response = MagicMock()
    mock_response.text = "song123"  # song_id 命中，避免落地页守卫
    mock_response.status_code = 200
    # 构造一个无 roleNames 的页面 → 哨兵
    mock_response.text = '<html><script id="serialized-server-data">{"data":[{"data":{"sections":[]}}]}</script></html>'
    mock_client.get.return_value = mock_response
    mock_client.aclose = AsyncMock()

    with patch("backend.meta.credits._fetch_single_region", new_callable=AsyncMock) as m:
        # 模拟 _fetch_single_region 返回哨兵
        from backend.meta.credits import _NO_CREDITS_SENTINEL
        m.return_value = _NO_CREDITS_SENTINEL
        result = await fetch_credits(
            "song123", "us", client=mock_client, base_url="https://injected.proxy"
        )
        # 哨兵路径下 fetch_credits 返回哨兵
        assert result is not None
        # 确认 _fetch_single_region 收到注入的 base_url
        m.assert_awaited_once()
        call_kwargs = m.call_args
        assert call_kwargs.kwargs.get("base_url") == "https://injected.proxy"
