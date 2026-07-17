"""测试——config 端点（版本号注入）。"""

from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend._version import get_version
from backend.server.config_routes import config_router

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """返回挂了 config_router 的 httpx client。"""
    app = FastAPI()
    app.include_router(config_router, prefix="/api")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_config_returns_version(client: AsyncClient) -> None:
    """GET /api/config 含 version 字段，值与 _version.get_version() 一致。"""
    resp = await client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert "version" in body
    assert body["version"] == get_version()


async def test_version_nonempty_string() -> None:
    """_version.VERSION 是非空字符串（注入或回落 0.1.0，不空不 None）。"""
    v = get_version()
    assert isinstance(v, str)
    assert v != ""
