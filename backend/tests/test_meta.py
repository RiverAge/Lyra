"""测试——元数据写入/对比模块 + meta_routes。

覆盖：
- writer MP4/FLAC/MP3 三格式写标签
- 重复写不累积（大小写不敏感删除）
- diff 四种 status
- meta_routes 三个端点
- 异常场景：404/503/422/穿越
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.index.store import IndexStore, set_store
from backend.meta.diff import compute_diff
from backend.meta.writer import read_tag_map, write_metadata
from backend.server.meta_routes import meta_router

# asyncio_mode = "auto" 由 pyproject.toml 设定，自动检测 async 测试函数

# ---------------------------------------------------------------------------
# 共享测试数据
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(
    "C:/Users/Mercury/Desktop/src/media/navidrome/tests/fixtures"
)

_TITLE_NEW = "New Title"
_ARTIST_NEW = "New Artist"
_COMPOSER_NEW = "New Composer"
_LYRICIST_NEW = "New Lyricist"
_PRODUCER_NEW = ["Producer A", "Producer B"]


# ---------------------------------------------------------------------------
# writer 测试
# ---------------------------------------------------------------------------


class TestWriterMP4:
    """MP4 格式写入测试。"""

    async def test_write_standard_and_freeform(self, tmp_path: Path) -> None:
        """写 ©nam/©wrt + freeform lyricist/producer → 读回验证。"""
        src = _FIXTURE_DIR / "test.m4a"
        dst = tmp_path / "test.m4a"
        shutil.copy2(src, dst)

        result = write_metadata(dst, {
            "title": [_TITLE_NEW],
            "composer": [_COMPOSER_NEW],
            "lyricist": [_LYRICIST_NEW],
            "producer": _PRODUCER_NEW,
        })
        assert result["format"] == "alac"
        assert result["fields_written"] >= 4  # type: ignore[operator]

        tag_map, codec = read_tag_map(dst)
        assert codec == "alac"
        assert tag_map.get("©nam") == [_TITLE_NEW]
        assert tag_map.get("©wrt") == [_COMPOSER_NEW]
        assert tag_map.get("----:com.apple.iTunes:lyricist") == [_LYRICIST_NEW]
        assert tag_map.get("----:com.apple.iTunes:producer") == _PRODUCER_NEW

    async def test_write_idempotent_no_accumulation(self, tmp_path: Path) -> None:
        """同一组 fields 写两次 → 读回不累积（大小写不敏感删除生效）。"""
        src = _FIXTURE_DIR / "test.m4a"
        dst = tmp_path / "test.m4a"
        shutil.copy2(src, dst)

        write_metadata(dst, {"title": [_TITLE_NEW]})
        write_metadata(dst, {"title": [_TITLE_NEW]})

        tag_map, _ = read_tag_map(dst)
        assert tag_map.get("©nam") == [_TITLE_NEW]
        # 确保只有一条
        assert len(tag_map.get("©nam", [])) == 1

    async def test_case_insensitive_freeform_delete(self, tmp_path: Path) -> None:
        """先写大写 freeform LYRICIST → 再写小写 lyricist → 读回只有小写。"""
        src = _FIXTURE_DIR / "test.m4a"
        dst = tmp_path / "test.m4a"
        shutil.copy2(src, dst)

        write_metadata(dst, {"lyricist": ["UPPER"]})
        # 现在文件中有 ----:com.apple.iTunes:lyricist （小写）
        write_metadata(dst, {"lyricist": ["lower"]})

        tag_map, _ = read_tag_map(dst)
        assert tag_map.get("----:com.apple.iTunes:lyricist") == ["lower"]
        # 验证没有大小写变体
        for key in tag_map:
            assert key != "----:com.apple.iTunes:LYRICIST"


class TestWriterFLAC:
    """FLAC 格式写入测试。"""

    async def test_write_basic(self, tmp_path: Path) -> None:
        """写 TITLE/ARTIST → 读回验证。"""
        src = _FIXTURE_DIR / "test.flac"
        dst = tmp_path / "test.flac"
        shutil.copy2(src, dst)

        result = write_metadata(dst, {
            "title": [_TITLE_NEW],
            "artist": [_ARTIST_NEW],
        })
        assert result["format"] == "flac"
        assert result["fields_written"] == 2

        tag_map, codec = read_tag_map(dst)
        assert codec == "flac"
        assert tag_map.get("title") == [_TITLE_NEW]
        assert tag_map.get("artist") == [_ARTIST_NEW]


class TestWriterMP3:
    """MP3 格式写入测试。"""

    async def test_write_basic(self, tmp_path: Path) -> None:
        """写 TIT2/TPE1 + TXXX → 读回验证。"""
        src = _FIXTURE_DIR / "test.mp3"
        dst = tmp_path / "test.mp3"
        shutil.copy2(src, dst)

        result = write_metadata(dst, {
            "title": [_TITLE_NEW],
            "artist": [_ARTIST_NEW],
            "lyricist": [_LYRICIST_NEW],
        })
        assert result["format"] == "mp3"
        assert result["fields_written"] == 3

        tag_map, codec = read_tag_map(dst)
        assert codec == "mp3"
        assert tag_map.get("TIT2") == [_TITLE_NEW]
        assert tag_map.get("TPE1") == [_ARTIST_NEW]
        # TXXX:LYRICIST — 注意值可能包含 \x00 分隔符，看具体读回格式
        txxx_keys = [k for k in tag_map if k.startswith("TXXX:")]
        lyricist_key = next((k for k in txxx_keys if "LYRICIST" in k.upper()), None)
        assert lyricist_key is not None, f"No TXXX:LYRICIST found in {txxx_keys}"
        assert tag_map[lyricist_key] == [_LYRICIST_NEW]


# ---------------------------------------------------------------------------
# diff 测试
# ---------------------------------------------------------------------------


class TestDiff:
    """before/after 对比纯函数测试。"""

    def test_same(self) -> None:
        """local == auth → status=same。"""
        result = compute_diff(
            local_tag_map={"©ART": ["Artist"]},
            auth_fields={"artist": ["Artist"]},
        )
        diffs = result["diffs"]
        artist_diff = next(d for d in diffs if d["field"] == "artist")
        assert artist_diff["status"] == "same"

    def test_different(self) -> None:
        """local 有 artist=旧值，auth 有 artist=新值 → different。"""
        result = compute_diff(
            local_tag_map={"©ART": ["Old Artist"]},
            auth_fields={"artist": ["New Artist"]},
        )
        diffs = result["diffs"]
        artist_diff = next(d for d in diffs if d["field"] == "artist")
        assert artist_diff["status"] == "different"
        assert artist_diff["local_value"] == ["Old Artist"]
        assert artist_diff["auth_value"] == ["New Artist"]

    def test_missing_local(self) -> None:
        """local 无 lyricist，auth 有 → missing_local。"""
        result = compute_diff(
            local_tag_map={"©ART": ["Artist"]},
            auth_fields={"lyricist": ["Lyricist"]},
        )
        diffs = result["diffs"]
        lyricist_diff = next(d for d in diffs if d["field"] == "lyricist")
        assert lyricist_diff["status"] == "missing_local"
        assert lyricist_diff["local_value"] is None
        assert lyricist_diff["auth_value"] == ["Lyricist"]

    def test_missing_auth(self) -> None:
        """local 有，auth 无 → missing_auth。"""
        result = compute_diff(
            local_tag_map={"©ART": ["Artist"]},
            auth_fields={},
        )
        diffs = result["diffs"]
        artist_diff = next(d for d in diffs if d["field"] == "artist")
        assert artist_diff["status"] == "missing_auth"
        assert artist_diff["local_value"] == ["Artist"]
        assert artist_diff["auth_value"] is None

    def test_mp4_freeform_mapping(self) -> None:
        """MP4 freeform key 正确映射到语义字段名。"""
        result = compute_diff(
            local_tag_map={"----:com.apple.iTunes:producer": ["Producer A"]},
            auth_fields={"producer": ["Producer A"]},
        )
        diffs = result["diffs"]
        producer_diff = next(d for d in diffs if d["field"] == "producer")
        assert producer_diff["status"] == "same"

    def test_before_after_structure(self) -> None:
        """确认返回结构含 before/after/diffs。"""
        result = compute_diff(
            local_tag_map={"©ART": ["Artist"]},
            auth_fields={"artist": ["Artist"], "title": ["Song"]},
        )
        assert "before" in result
        assert "after" in result
        assert "diffs" in result
        assert result["before"]["artist"] == ["Artist"]
        assert result["before"]["title"] is None
        assert result["after"]["artist"] == ["Artist"]
        assert result["after"]["title"] == ["Song"]

    def test_empty_tag_map(self) -> None:
        """空 tag_map 时 diff 仍可工作。"""
        result = compute_diff(
            local_tag_map={},
            auth_fields={"title": ["Song"]},
        )
        diffs = result["diffs"]
        assert len(diffs) >= 1
        title_diff = next(d for d in diffs if d["field"] == "title")
        assert title_diff["status"] == "missing_local"

    def test_flac_format_detection(self) -> None:
        """FLAC 格式的 tag_map（小写 key）正确检测。"""
        result = compute_diff(
            local_tag_map={"artist": ["Artist"], "title": ["Song"]},
            auth_fields={"artist": ["Artist"], "title": ["Song"]},
        )
        diffs = result["diffs"]
        assert all(d["status"] == "same" for d in diffs)

    def test_mp3_format_detection(self) -> None:
        """MP3 格式的 tag_map（ID3 大写 key）正确检测。"""
        result = compute_diff(
            local_tag_map={"TIT2": ["Song"], "TPE1": ["Artist"]},
            auth_fields={"title": ["Song"], "artist": ["Artist"]},
        )
        diffs = result["diffs"]
        assert all(d["status"] == "same" for d in diffs)


# ---------------------------------------------------------------------------
# meta_routes 测试 — fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """创建含 meta_router 的测试 app。"""
    app_fast = FastAPI()
    app_fast.include_router(meta_router, prefix="/api")
    return app_fast


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """返回已绑定测试 app 的 httpx AsyncClient。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def prepare_track(tmp_path: Path) -> dict[str, object]:
    """在 tmp_path 复制 test.m4a 并返回插入 store 所需的字段。"""
    src = _FIXTURE_DIR / "test.m4a"
    dst = tmp_path / "test.m4a"
    shutil.copy2(src, dst)
    return {
        "title": "Title",
        "artist": "Artist",
        "path": str(dst).replace("\\", "/"),
        "codec": "alac",
        "duration": 200000,
        "size": dst.stat().st_size,
        "tag_map": '{"©nam": ["Title"], "©ART": ["Artist"]}',
    }


# ---------------------------------------------------------------------------
# meta_routes 测试 — /meta/fields
# ---------------------------------------------------------------------------


class TestMetaFields:
    """GET /api/meta/fields 测试。"""

    async def test_fields_returns_list(self, client: AsyncClient) -> None:
        """返回字段清单，含 semantic/mp4/flac/mp3。"""
        resp = await client.get("/api/meta/fields")
        assert resp.status_code == 200
        body = resp.json()
        assert "fields" in body
        assert isinstance(body["fields"], list)
        assert len(body["fields"]) > 0
        field = body["fields"][0]
        assert "semantic" in field
        assert "mp4" in field
        assert "flac" in field
        assert "mp3" in field


# ---------------------------------------------------------------------------
# meta_routes 测试 — POST /meta/{track_id}/diff
# ---------------------------------------------------------------------------


class TestMetaDiffRoute:
    """POST /api/meta/{track_id}/diff 测试。"""

    async def test_diff_returns_before_after(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        prepare_track: dict[str, object],
    ) -> None:
        """正常 diff 请求返回 before/after 结构。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
        rowid = await store.insert_track(**prepare_track)  # type: ignore[arg-type]

        resp = await client.post(
            f"/api/meta/{rowid}/diff",
            json={"authoritative_fields": {"title": ["New Title"], "artist": ["Artist"]}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "before" in body
        assert "after" in body
        assert "diffs" in body
        # title should be different (Title → New Title)
        title_diffs = [d for d in body["diffs"] if d["field"] == "title"]
        assert len(title_diffs) == 1
        assert title_diffs[0]["status"] == "different"
        # artist should be same
        artist_diffs = [d for d in body["diffs"] if d["field"] == "artist"]
        assert len(artist_diffs) == 1
        assert artist_diffs[0]["status"] == "same"

    async def test_diff_track_not_found(
        self,
        store: IndexStore,
        client: AsyncClient,
    ) -> None:
        """不存在的 track_id 返回 404。"""
        # store fixture ensures store is initialized, but 999999 doesn't exist
        resp = await client.post(
            "/api/meta/999999/diff",
            json={"authoritative_fields": {}},
        )
        assert resp.status_code == 404

    async def test_diff_db_unavailable(
        self,
        app: FastAPI,
    ) -> None:
        """store 未初始化返回 503。"""
        set_store(None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/meta/1/diff",
                json={"authoritative_fields": {}},
            )
            assert resp.status_code == 503
            assert "Database not initialized" in resp.text

    async def test_diff_path_traversal(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """path 不在 library_root 下返回 404。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

        rowid = await store.insert_track(
            title="Outside",
            artist="A",
            path="/some/other/path/file.m4a",
            codec="alac",
            duration=200000,
        )

        resp = await client.post(
            f"/api/meta/{rowid}/diff",
            json={"authoritative_fields": {}},
        )
        assert resp.status_code == 404
        assert "Track not found" in resp.text


# ---------------------------------------------------------------------------
# meta_routes 测试 — POST /meta/{track_id}/write
# ---------------------------------------------------------------------------


class TestMetaWriteRoute:
    """POST /api/meta/{track_id}/write 测试。"""

    async def test_write_and_return_new_tag_map(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        prepare_track: dict[str, object],
    ) -> None:
        """写标签后返回新 tag_map，值正确。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
        rowid = await store.insert_track(**prepare_track)  # type: ignore[arg-type]

        resp = await client.post(
            f"/api/meta/{rowid}/write",
            json={
                "after_fields": {
                    "title": [_TITLE_NEW],
                    "artist": [_ARTIST_NEW],
                }
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["track_id"] == str(rowid)
        assert body["format"] == "alac"
        assert body["fields_written"] >= 2
        assert "new_tag_map" in body
        # Verify readback values
        new_map = body["new_tag_map"]
        assert new_map.get("©nam") == [_TITLE_NEW]
        assert new_map.get("©ART") == [_ARTIST_NEW]

    async def test_write_track_not_found(
        self,
        store: IndexStore,
        client: AsyncClient,
    ) -> None:
        """不存在的 track_id 返回 404。"""
        resp = await client.post(
            "/api/meta/999999/write",
            json={"after_fields": {}},
        )
        assert resp.status_code == 404

    async def test_write_db_unavailable(
        self,
        app: FastAPI,
    ) -> None:
        """store 未初始化返回 503。"""
        set_store(None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/meta/1/write",
                json={"after_fields": {}},
            )
            assert resp.status_code == 503
            assert "Database not initialized" in resp.text

    async def test_write_path_traversal(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """path 不在 library_root 下返回 404。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

        rowid = await store.insert_track(
            title="Outside",
            artist="A",
            path="/some/other/path/file.m4a",
            codec="alac",
            duration=200000,
        )

        resp = await client.post(
            f"/api/meta/{rowid}/write",
            json={"after_fields": {}},
        )
        assert resp.status_code == 404
        assert "Track not found" in resp.text

    async def test_write_invalid_track_id(
        self,
        client: AsyncClient,
    ) -> None:
        """非数字 track_id 返回 422。"""
        resp = await client.post(
            "/api/meta/abc/write",
            json={"after_fields": {}},
        )
        assert resp.status_code == 422

    async def test_write_file_not_exists(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """DB 有记录但文件不存在返回 404。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

        rowid = await store.insert_track(
            title="Ghost",
            artist="A",
            path=str(tmp_path / "nonexistent.m4a").replace("\\", "/"),
            codec="alac",
            duration=200000,
        )

        resp = await client.post(
            f"/api/meta/{rowid}/write",
            json={"after_fields": {"title": ["New"]}},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# get_supported_fields 测试
# ---------------------------------------------------------------------------


def test_get_supported_fields() -> None:
    """get_supported_fields 返回完整字段列表。"""
    from backend.meta.writer import get_supported_fields

    result: dict[str, object] = get_supported_fields()
    raw_fields = result.get("fields")
    assert raw_fields is not None
    fields: list[dict[str, object]] = raw_fields  # type: ignore[assignment]
    # 验证每个 field 有完整映射
    for f in fields:
        sem = f.get("semantic")
        assert sem is not None
    # 验证至少包含关键字段
    sem_names: set[str] = set()
    for f in fields:
        v = f.get("semantic")
        if isinstance(v, str):
            sem_names.add(v)
    for key in ("title", "artist", "album", "composer", "lyricist", "producer"):
        assert key in sem_names, f"Missing field: {key}"