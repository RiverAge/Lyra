"""测试——library 数据层。"""

from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.index.store import IndexStore, set_store

# 所有测试都需要 async 支持
pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# fixtures（test_library 特有；共享 fixtures 在 conftest.py）
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(app: FastAPI, store: IndexStore) -> AsyncGenerator[AsyncClient, None]:
    """返回已绑定测试 app 的 httpx AsyncClient。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


async def test_schema_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """schema 初始化幂等：连续调两次不报错。"""
    db_path = tmp_path / "test_idem.db"
    store = IndexStore(db_path)

    await store.init_schema()
    await store.init_schema()  # 第二次不应抛异常

    # 验证表确实存在
    count = await store.count_tracks()
    assert count == 0


async def test_library_empty(client: AsyncClient) -> None:
    """空库 GET /api/library 返回 200 + 空列表 + 正确分页结构。"""
    resp = await client.get("/api/library")
    assert resp.status_code == 200
    body = resp.json()

    assert body["items"] == []
    assert body["total"] == 0
    assert body["limit"] == 20
    assert body["offset"] == 0


async def test_library_with_track(store: IndexStore, client: AsyncClient) -> None:
    """插入一条 track 后 GET /api/library 能返回该记录，id 为 str。"""
    await store.insert_track(
        title="Test Song",
        artist="Test Artist",
        album_artist="Test Album Artist",
        album="Test Album",
        path="/music/apple/Artist/Album/01 Test.m4a",
        track=1,
        disc=1,
        year=2024,
        duration=240000,
        bitrate=256000,
        codec="alac",
        samplerate=44100,
        tag_map='{"©nam":"Test Song"}',
        mtime=1750000000000,
        size=25000000,
        has_cover=1,
        created_at=1750000000000,
        updated_at=1750000000000,
    )

    resp = await client.get("/api/library")
    assert resp.status_code == 200
    body = resp.json()

    assert body["total"] == 1
    assert len(body["items"]) == 1

    item = body["items"][0]
    # ID 必须是字符串（§3.4 契约）
    assert isinstance(item["id"], str)
    # 可再转回 int 验证是有效数字
    assert int(item["id"]) > 0

    assert item["title"] == "Test Song"
    assert item["artist"] == "Test Artist"
    assert item["album_artist"] == "Test Album Artist"
    assert item["album"] == "Test Album"
    assert item["path"] == "/music/apple/Artist/Album/01 Test.m4a"
    assert item["track"] == 1
    assert item["disc"] == 1
    assert item["year"] == 2024
    assert item["duration"] == 240000
    assert item["bitrate"] == 256000
    assert item["codec"] == "alac"
    assert item["samplerate"] == 44100
    assert item["tag_map"] == '{"©nam":"Test Song"}'
    assert item["mtime"] == 1750000000000
    assert item["size"] == 25000000
    assert item["has_cover"] == 1
    assert item["folder_hash"] is None
    assert item["created_at"] == 1750000000000
    assert item["updated_at"] == 1750000000000


async def test_library_pagination(store: IndexStore, client: AsyncClient) -> None:
    """分页：limit/offset 行为正确。"""
    # 插入 5 条记录
    for i in range(5):
        await store.insert_track(
            title=f"Song {i}",
            artist=f"Artist {i}",
            album_artist="",
            album="Album",
            path=f"/music/apple/Album/{i:02d} Song.m4a",
            track=i + 1,
            duration=200000 + i * 1000,
            created_at=1750000000000 + i,
            updated_at=1750000000000 + i,
        )

    # 第 1 页：limit=2, offset=0 → 2 items + total=5
    resp = await client.get("/api/library?limit=2&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert body["items"][0]["id"] == "1"
    assert body["items"][1]["id"] == "2"

    # 第 2 页：limit=2, offset=2 → 2 items
    resp = await client.get("/api/library?limit=2&offset=2")
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["total"] == 5
    assert body["items"][0]["id"] == "3"
    assert body["items"][1]["id"] == "4"

    # 第 3 页：limit=2, offset=4 → 1 item（最后一页）
    resp = await client.get("/api/library?limit=2&offset=4")
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["total"] == 5
    assert body["items"][0]["id"] == "5"

    # 超出范围：offset=10 → 空列表
    resp = await client.get("/api/library?limit=20&offset=10")
    body = resp.json()
    assert len(body["items"]) == 0
    assert body["total"] == 5


async def test_library_db_unavailable(app: FastAPI) -> None:
    """数据库未初始化（store=None）时返回 503。"""
    set_store(None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/library")
        assert resp.status_code == 503
        body = resp.json()
        assert "detail" in body
        assert "Database not initialized" in body["detail"]