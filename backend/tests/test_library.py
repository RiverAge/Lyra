"""测试——library 数据层。"""

from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.index.store import IndexStore, set_store
from backend.server.library_routes import _stats_cache

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
    # 列表端点不返回 tag_map（可能含内嵌歌词等大 JSON，20 首可达 100MB+）。
    # tag_map 在单首详情 /library/{id} 返回供 MetaTab 用。同时不返回
    # mtime/folder_hash/created_at/updated_at（内部字段）。
    assert "tag_map" not in item
    assert "mtime" not in item
    assert "folder_hash" not in item
    assert "created_at" not in item
    assert "updated_at" not in item
    assert item["size"] == 25000000
    assert item["has_cover"] == 1


async def test_library_search_empty_q(client: AsyncClient) -> None:
    """空 query → items=[]，不报错。"""
    resp = await client.get("/api/library/search?q=")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []


async def test_library_search_matches(store: IndexStore, client: AsyncClient) -> None:
    """搜索跨 title/artist/album 都能命中，返回列表列集（无 tag_map）。"""
    await store.insert_track(
        title="Lemon",
        artist="米津玄師",
        album_artist="米津玄師",
        album="Lemon EP",
        path="/music/yonezu/lemon/01.m4a",
        track=1,
        duration=240000,
        codec="alac",
        mtime=1750000000000,
        size=1000,
        has_cover=1,
        created_at=1750000000000,
        updated_at=1750000000000,
    )
    await store.insert_track(
        title="Loser",
        artist="Other Artist",
        album_artist="Other Artist",
        album="Random",
        path="/music/other/loser.m4a",
        track=1,
        duration=200000,
        codec="alac",
        mtime=1750000000000,
        size=1000,
        has_cover=1,
        created_at=1750000000000,
        updated_at=1750000000000,
    )

    # title 命中
    resp = await client.get("/api/library/search?q=Lemon")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Lemon"
    assert "tag_map" not in items[0]  # 列表列集

    # artist 命中
    resp = await client.get("/api/library/search?q=米津")
    assert len(resp.json()["items"]) == 1

    # album 命中
    resp = await client.get("/api/library/search?q=Random")
    assert len(resp.json()["items"]) == 1

    # 无匹配
    resp = await client.get("/api/library/search?q=NoSuchSong")
    assert resp.json()["items"] == []


async def test_library_search_before_track_id_route(
    store: IndexStore, client: AsyncClient,
) -> None:
    """路由顺序：/library/search 不被 /library/{track_id} 吞掉（search 非 track_id）。"""
    await store.insert_track(
        title="T",
        artist="A",
        album_artist="A",
        album="Al",
        path="/music/s/01.m4a",
        track=1,
        duration=100000,
        codec="alac",
        mtime=1750000000000,
        size=1000,
        has_cover=0,
        created_at=1750000000000,
        updated_at=1750000000000,
    )
    # /library/search 应 200（不是 422 把 search 当 track_id）
    resp = await client.get("/api/library/search?q=T")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1


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


# ---------------------------------------------------------------------------
# GET /api/library/{track_id} 单 track 端点
# ---------------------------------------------------------------------------


async def _insert_sample_track(store: IndexStore, *, path: str, rowid_offset: int = 0) -> int:
    """插入一条样本 track 并返回其 rowid（用于断言）。"""
    # rowid_offset 仅用于让 path 唯一（避免 UNIQUE 冲突）
    return await store.insert_track(
        title="Test Song",
        artist="Test Artist",
        album_artist="Test Album Artist",
        album="Test Album",
        path=path,
        track=1,
        disc=1,
        year=2024,
        duration=240000,
        bitrate=256000,
        codec="alac",
        samplerate=44100,
        mtime=1750000000000,
        size=25000000,
        has_cover=1,
        created_at=1750000000000,
        updated_at=1750000000000 + rowid_offset,
    )


async def test_get_track_by_id_ok(store: IndexStore, client: AsyncClient) -> None:
    """GET /api/library/{id} 命中存在 track，返回完整字段且 id 为 str。"""
    rowid = await _insert_sample_track(
        store,
        path="/music/apple/Artist/Album/01 Test.m4a",
    )

    resp = await client.get(f"/api/library/{rowid}")
    assert resp.status_code == 200
    item = resp.json()

    assert isinstance(item["id"], str)
    assert item["id"] == str(rowid)
    assert item["title"] == "Test Song"
    assert item["artist"] == "Test Artist"
    assert item["album"] == "Test Album"
    assert item["path"] == "/music/apple/Artist/Album/01 Test.m4a"
    assert item["duration"] == 240000
    assert item["codec"] == "alac"
    # B 方案：详情端点不返回 tag_map（不入库，MetaTab 现读 /meta/{id}/tags）
    assert "tag_map" not in item


async def test_get_track_by_id_not_found(client: AsyncClient) -> None:
    """GET /api/library/{id} 不存在 → 404。"""
    resp = await client.get("/api/library/999999")
    assert resp.status_code == 404
    body = resp.json()
    assert "not found" in body["detail"].lower()


async def test_get_track_by_id_invalid_id(client: AsyncClient) -> None:
    """GET /api/library/{id} 非整数 id → 422。"""
    resp = await client.get("/api/library/abc")
    assert resp.status_code == 422
    body = resp.json()
    assert "invalid" in body["detail"].lower()


async def test_get_track_db_unavailable(app: FastAPI) -> None:
    """数据库未初始化时 GET /api/library/{id} 返回 503。"""
    set_store(None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/library/1")
        assert resp.status_code == 503
        body = resp.json()
        assert "Database not initialized" in body["detail"]


# ---------------------------------------------------------------------------
# GET /api/library/stats — 聚合统计 + 扫描期缓存
# ---------------------------------------------------------------------------


async def test_library_stats_basic(store: IndexStore, client: AsyncClient) -> None:
    """空闲态 stats 返回正确聚合值，且缓存被填充。"""
    _stats_cache.value = None  # 清缓存防其他测试污染
    await store.insert_track(
        title="A",
        artist="X",
        album_artist="X",
        album="Album1",
        path="/music/Album1/01.m4a",
        track=1,
        duration=100000,
        codec="alac",
        created_at=1750000000000,
        updated_at=1750000000000,
    )

    resp = await client.get("/api/library/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["track_count"] == 1
    assert body["album_count"] == 1
    assert body["total_duration_sec"] == 100  # 100000ms / 1000
    assert body["lossless_ratio"] == 1.0  # alac 无损
    # 空闲态查完 DB 应填充缓存
    assert _stats_cache.value is not None


async def test_library_stats_cached_during_scan(
    store: IndexStore, client: AsyncClient,
) -> None:
    """扫描中且缓存有值 → 返回缓存（跳过全表扫），不查 DB。

    构造：先查一次 stats 填充缓存，再置 scanning，删表行，
    再次 stats 应返回缓存的旧值（而非 0）——证明没查 DB。
    """
    _stats_cache.value = None
    await store.insert_track(
        title="A",
        artist="X",
        album_artist="X",
        album="Album1",
        path="/music/Album1/01.m4a",
        track=1,
        duration=100000,
        codec="alac",
        created_at=1750000000000,
        updated_at=1750000000000,
    )
    # 第一次查 → 填充缓存（track_count=1）
    resp1 = await client.get("/api/library/stats")
    assert resp1.json()["track_count"] == 1

    # 置扫描中
    await store.set_scanner_status(state="scanning", scan_type="full")

    # 删光 tracks 行——若 stats 走 DB 会返回 0；走缓存应仍是 1
    await _db_exec(store, "DELETE FROM tracks")
    resp2 = await client.get("/api/library/stats")
    assert resp2.status_code == 200
    assert resp2.json()["track_count"] == 1  # 缓存值，非 DB 实时值

    _stats_cache.value = None  # 清缓存防泄漏


async def _db_exec(store: IndexStore, sql: str) -> None:
    """测试辅助：直接执行裸 SQL（清表用）。"""
    import aiosqlite

    async with aiosqlite.connect(store._db_path) as db:  # noqa: SLF001
        await db.execute(sql)
        await db.commit()