"""测试——播放层静态流端点。

覆盖 GET /api/play/{track_id} 的静态流 + Range 逻辑，
以及 HEAD /api/play/{track_id} 的 header-only 响应。

使用构造的测试文件（非真实音频，因为流端点不关心文件内容，
只关心字节 range 是否正确。codec 来自 DB 记录而非文件头）。
"""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.index.store import IndexStore, set_store
from backend.play.stream import play_router

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """创建含 play_router 的测试 app。

    未包含 library_router/scanner_router——本文件只测播放端点。
    """
    app = FastAPI()
    app.include_router(play_router, prefix="/api")
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """返回已绑定测试 app 的 httpx AsyncClient。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_test_file(path: Path, size: int = 256) -> None:
    """创建指定大小的测试文件，内容为重复 'A'。"""
    path.write_bytes(b"A" * size)


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


async def test_play_get_no_range_200(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """无 Range GET 返回 200 + Content-Length + Accept-Ranges + 正确 Content-Type。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
    test_file = tmp_path / "test.m4a"
    _make_test_file(test_file, size=1000)

    rowid = await store.insert_track(
        title="Test",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="alac",
        duration=200000,
        size=1000,
    )

    resp = await client.get(f"/api/play/{rowid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mp4"
    assert resp.headers["content-length"] == "1000"
    assert resp.headers["accept-ranges"] == "bytes"
    assert len(resp.content) == 1000


async def test_play_get_range_206(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """有 Range GET 返回 206 + Content-Range + 正确字节。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
    test_file = tmp_path / "test.m4a"
    _make_test_file(test_file, size=1000)

    rowid = await store.insert_track(
        title="Test",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="alac",
        duration=200000,
        size=1000,
    )

    resp = await client.get(
        f"/api/play/{rowid}",
        headers={"Range": "bytes=0-99"},
    )
    assert resp.status_code == 206
    assert resp.headers["content-range"] == "bytes 0-99/1000"
    assert resp.headers["content-length"] == "100"
    assert resp.headers["content-type"] == "audio/mp4"
    assert resp.headers["accept-ranges"] == "bytes"
    assert len(resp.content) == 100
    assert resp.content == b"A" * 100


async def test_play_range_start_open(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """bytes=start- 开区间语法。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
    test_file = tmp_path / "test.m4a"
    _make_test_file(test_file, size=1000)

    rowid = await store.insert_track(
        title="Test",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="alac",
        duration=200000,
        size=1000,
    )

    resp = await client.get(
        f"/api/play/{rowid}",
        headers={"Range": "bytes=900-"},
    )
    assert resp.status_code == 206
    assert resp.headers["content-range"] == "bytes 900-999/1000"
    assert resp.headers["content-length"] == "100"
    assert len(resp.content) == 100


async def test_play_range_suffix(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """bytes=-suffix 后缀语法。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
    test_file = tmp_path / "test.m4a"
    _make_test_file(test_file, size=1000)

    rowid = await store.insert_track(
        title="Test",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="alac",
        duration=200000,
        size=1000,
    )

    resp = await client.get(
        f"/api/play/{rowid}",
        headers={"Range": "bytes=-100"},
    )
    assert resp.status_code == 206
    assert resp.headers["content-range"] == "bytes 900-999/1000"
    assert resp.headers["content-length"] == "100"
    assert len(resp.content) == 100


async def test_play_range_out_of_bounds(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """越界 Range 返回 416。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
    test_file = tmp_path / "test.m4a"
    _make_test_file(test_file, size=1000)

    rowid = await store.insert_track(
        title="Test",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="alac",
        duration=200000,
        size=1000,
    )

    # 开区间越界
    resp = await client.get(
        f"/api/play/{rowid}",
        headers={"Range": "bytes=999999999-"},
    )
    assert resp.status_code == 416

    # start > end
    resp2 = await client.get(
        f"/api/play/{rowid}",
        headers={"Range": "bytes=100-50"},
    )
    assert resp2.status_code == 416


async def test_play_head(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """HEAD 返回 header 不返 body。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
    test_file = tmp_path / "test.m4a"
    _make_test_file(test_file, size=1000)

    rowid = await store.insert_track(
        title="Test",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="alac",
        duration=200000,
        size=1000,
    )

    resp = await client.head(f"/api/play/{rowid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mp4"
    assert resp.headers["content-length"] == "1000"
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.content == b""


async def test_play_track_not_found(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """不存在的 track_id 返回 404。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
    resp = await client.get("/api/play/999999")
    assert resp.status_code == 404
    assert "Track not found" in resp.text


async def test_play_db_unavailable(app: FastAPI) -> None:
    """store 未初始化返回 503。"""
    set_store(None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/play/1")
        assert resp.status_code == 503
        assert "Database not initialized" in resp.text


async def test_play_path_traversal(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """path 不在 library_root 下时返回 404（不泄露路径细节）。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

    rowid = await store.insert_track(
        title="Outside",
        artist="A",
        path="/some/other/path/file.m4a",
        codec="alac",
        duration=200000,
    )

    resp = await client.get(f"/api/play/{rowid}")
    assert resp.status_code == 404
    assert "Track not found" in resp.text


async def test_play_file_not_exists(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """DB 有记录但文件在磁盘上不存在返回 404。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

    rowid = await store.insert_track(
        title="Ghost",
        artist="A",
        path=str(tmp_path / "nonexistent.m4a").replace("\\", "/"),
        codec="alac",
        duration=200000,
    )

    resp = await client.get(f"/api/play/{rowid}")
    assert resp.status_code == 404
    assert "Track not found" in resp.text


async def test_play_codec_content_type(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """不同 codec 字段对应正确的 Content-Type。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

    # alac → audio/mp4
    f_a = tmp_path / "a.m4a"
    _make_test_file(f_a, size=100)
    rid1 = await store.insert_track(
        title="A", artist="A", path=str(f_a).replace("\\", "/"),
        codec="alac", duration=200000, size=100,
    )
    resp = await client.get(f"/api/play/{rid1}")
    assert resp.headers["content-type"] == "audio/mp4"

    # flac → audio/flac
    f_b = tmp_path / "b.flac"
    _make_test_file(f_b, size=100)
    rid2 = await store.insert_track(
        title="B", artist="B", path=str(f_b).replace("\\", "/"),
        codec="flac", duration=200000, size=100,
    )
    resp = await client.get(f"/api/play/{rid2}")
    assert resp.headers["content-type"] == "audio/flac"

    # mp3 → audio/mpeg
    f_c = tmp_path / "c.mp3"
    _make_test_file(f_c, size=100)
    rid3 = await store.insert_track(
        title="C", artist="C", path=str(f_c).replace("\\", "/"),
        codec="mp3", duration=200000, size=100,
    )
    resp = await client.get(f"/api/play/{rid3}")
    assert resp.headers["content-type"] == "audio/mpeg"

    # None → application/octet-stream
    f_d = tmp_path / "d.unknown"
    _make_test_file(f_d, size=100)
    rid4 = await store.insert_track(
        title="D", artist="D", path=str(f_d).replace("\\", "/"),
        codec=None, duration=200000, size=100,
    )
    resp = await client.get(f"/api/play/{rid4}")
    assert resp.headers["content-type"] == "application/octet-stream"


async def test_play_invalid_track_id(
    client: AsyncClient,
) -> None:
    """非数字 track_id 返回 422（FastAPI 路径校验默认行为）。"""
    resp = await client.get("/api/play/abc")
    assert resp.status_code == 422


async def test_play_library_root_not_configured(
    store: IndexStore, client: AsyncClient, monkeypatch  # type: ignore[no-untyped-def]
) -> None:
    """library_root 未配置时返回 503。"""
    monkeypatch.delenv("LYRA_MUSIC_LIBRARY_ROOT", raising=False)

    rowid = await store.insert_track(
        title="Test",
        artist="A",
        path="/some/path.m4a",
        codec="alac",
        duration=200000,
    )

    resp = await client.get(f"/api/play/{rowid}")
    assert resp.status_code == 503
    assert "Library root not configured" in resp.text


async def test_play_head_with_range(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """HEAD 请求带 Range 返回 206 header 不返 body。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
    test_file = tmp_path / "test.m4a"
    _make_test_file(test_file, size=1000)

    rowid = await store.insert_track(
        title="Test",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="alac",
        duration=200000,
        size=1000,
    )

    resp = await client.head(
        f"/api/play/{rowid}",
        headers={"Range": "bytes=0-99"},
    )
    assert resp.status_code == 206
    assert resp.headers["content-range"] == "bytes 0-99/1000"
    assert resp.headers["content-length"] == "100"
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.content == b""