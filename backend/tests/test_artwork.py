"""测试——library artwork 端点（GET /api/library/{id}/artwork）。

覆盖端点逻辑（路径校验 / 404 / 503 / Response 构造）。
mutagen 读封面 bytes 的真实链路由 scanner 集成测试覆盖（test_scanner.py），
此处 mock _read_cover_bytes_sync 避免构造完整 MP4 容器的复杂度。
"""

from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.index.store import IndexStore, set_store
from backend.server import library_routes
from backend.server.library_routes import library_router

pytestmark = pytest.mark.asyncio

# 最小 1×1 JPEG SOI+EOI（用于 mock 返回值）
_JPEG_BYTES = b"\xff\xd8\xff\xd9"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """创建含 library_router 的测试 app。"""
    app = FastAPI()
    app.include_router(library_router, prefix="/api")
    return app


@pytest.fixture
async def store(tmp_path: object) -> AsyncGenerator[IndexStore, None]:
    """在临时目录创建已初始化的 IndexStore。"""
    db_path = tmp_path / "test_artwork.db"  # type: ignore[operator]
    s = IndexStore(db_path)  # type: ignore[arg-type]
    await s.init_schema()
    set_store(s)
    yield s
    set_store(None)


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


async def test_artwork_returns_cover_bytes(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """有封面的 track → 200 + image/jpeg + 封面 bytes。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
    test_file = tmp_path / "with_cover.m4a"
    test_file.write_bytes(b"fake mp4")  # 文件存在即可，mutagen 被 mock

    rowid = await store.insert_track(
        title="With Cover",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="alac",
        duration=200000,
        has_cover=1,
    )

    # mock mutagen 读封面函数
    monkeypatch.setattr(
        library_routes,
        "_read_cover_bytes_sync",
        lambda path: (_JPEG_BYTES, "image/jpeg"),
    )

    resp = await client.get(f"/api/library/{rowid}/artwork")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content == _JPEG_BYTES


async def test_artwork_no_cover_returns_404(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """has_cover=0 → 404 No cover art。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
    test_file = tmp_path / "no_cover.m4a"
    test_file.write_bytes(b"fake mp4")

    rowid = await store.insert_track(
        title="No Cover",
        artist="B",
        path=str(test_file).replace("\\", "/"),
        codec="alac",
        duration=200000,
        has_cover=0,
    )

    resp = await client.get(f"/api/library/{rowid}/artwork")
    assert resp.status_code == 404
    assert "No cover art" in resp.json()["detail"]


async def test_artwork_track_not_found(
    store: IndexStore, client: AsyncClient,  # type: ignore[no-untyped-def]
) -> None:
    """track 不存在 → 404。"""
    resp = await client.get("/api/library/999999/artwork")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


async def test_artwork_invalid_id(client: AsyncClient) -> None:
    """track_id 非数字 → 422。"""
    resp = await client.get("/api/library/abc/artwork")
    assert resp.status_code == 422
    assert "invalid" in resp.json()["detail"].lower()


async def test_artwork_db_unavailable(app: FastAPI) -> None:
    """store=None → 503。"""
    set_store(None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/library/1/artwork")
        assert resp.status_code == 503
        assert "Database not initialized" in resp.json()["detail"]


async def test_artwork_file_missing_returns_404(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """has_cover=1 但文件已删除 → 404。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
    # 不创建文件，但 DB 记 has_cover=1
    rowid = await store.insert_track(
        title="Missing File",
        artist="C",
        path=str(tmp_path / "ghost.m4a").replace("\\", "/"),
        codec="alac",
        duration=200000,
        has_cover=1,
    )

    resp = await client.get(f"/api/library/{rowid}/artwork")
    assert resp.status_code == 404


async def test_artwork_mutagen_returns_none_404(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """has_cover=1 但 mutagen 读不到封面（文件损坏/格式不支持）→ 404。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
    test_file = tmp_path / "corrupt.m4a"
    test_file.write_bytes(b"not a real mp4")

    rowid = await store.insert_track(
        title="Corrupt",
        artist="D",
        path=str(test_file).replace("\\", "/"),
        codec="alac",
        duration=200000,
        has_cover=1,
    )

    # mock mutagen 返回 None（文件无封面或无法解析）
    monkeypatch.setattr(
        library_routes,
        "_read_cover_bytes_sync",
        lambda path: None,
    )

    resp = await client.get(f"/api/library/{rowid}/artwork")
    assert resp.status_code == 404
    assert "No cover art" in resp.json()["detail"]
