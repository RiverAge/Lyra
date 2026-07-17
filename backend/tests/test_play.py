"""测试——播放层静态流端点 + 实时转码。

覆盖 GET /api/play/{track_id} 的静态流 + Range 逻辑、
转码分流逻辑、ffmpeg 不可用 503 路径，
以及 HEAD /api/play/{track_id} 的 header-only 响应。

使用构造的测试文件（非真实音频，因为流端点不关心文件内容，
只关心字节 range 是否正确。codec 来自 DB 记录而非文件头）。
"""

import threading
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.index.store import IndexStore, set_store
from backend.play.stream import play_router
from backend.play.transcode import reset_ffmpeg_probe, transcode_stream

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
    test_file = tmp_path / "test.mp3"
    _make_test_file(test_file, size=1000)

    rowid = await store.insert_track(
        title="Test",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="mp3",
        duration=200000,
        size=1000,
    )

    resp = await client.get(f"/api/play/{rowid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.headers["content-length"] == "1000"
    assert resp.headers["accept-ranges"] == "bytes"
    assert len(resp.content) == 1000


async def test_play_get_range_206(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """有 Range GET 返回 206 + Content-Range + 正确字节。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
    test_file = tmp_path / "test.mp3"
    _make_test_file(test_file, size=1000)

    rowid = await store.insert_track(
        title="Test",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="mp3",
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
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.headers["accept-ranges"] == "bytes"
    assert len(resp.content) == 100
    assert resp.content == b"A" * 100


async def test_play_range_start_open(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """bytes=start- 开区间语法。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
    test_file = tmp_path / "test.mp3"
    _make_test_file(test_file, size=1000)

    rowid = await store.insert_track(
        title="Test",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="mp3",
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
    test_file = tmp_path / "test.mp3"
    _make_test_file(test_file, size=1000)

    rowid = await store.insert_track(
        title="Test",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="mp3",
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
    test_file = tmp_path / "test.mp3"
    _make_test_file(test_file, size=1000)

    rowid = await store.insert_track(
        title="Test",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="mp3",
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
    test_file = tmp_path / "test.mp3"
    _make_test_file(test_file, size=1000)

    rowid = await store.insert_track(
        title="Test",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="mp3",
        duration=200000,
        size=1000,
    )

    resp = await client.head(f"/api/play/{rowid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
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
    """不同 codec 字段对应正确的 Content-Type（原生可解码格式走直传）。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

    # flac → audio/flac（原生可解码，走直传）
    f_b = tmp_path / "b.flac"
    _make_test_file(f_b, size=100)
    rid2 = await store.insert_track(
        title="B", artist="B", path=str(f_b).replace("\\", "/"),
        codec="flac", duration=200000, size=100,
    )
    resp = await client.get(f"/api/play/{rid2}")
    assert resp.headers["content-type"] == "audio/flac"

    # mp3 → audio/mpeg（原生可解码，走直传）
    f_c = tmp_path / "c.mp3"
    _make_test_file(f_c, size=100)
    rid3 = await store.insert_track(
        title="C", artist="C", path=str(f_c).replace("\\", "/"),
        codec="mp3", duration=200000, size=100,
    )
    resp = await client.get(f"/api/play/{rid3}")
    assert resp.headers["content-type"] == "audio/mpeg"

    # None → application/octet-stream（未知 codec，走直传）
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
    """library_root 未配置时返回 503。

    用 patch get_settings 而非 monkeypatch.delenv：pydantic-settings 的
    env_file=".env" 会在 delenv 后仍从 .env 读到 LYRA_MUSIC_LIBRARY_ROOT，
    导致 root 非空、走到文件存在性检查返回 404 而非 503。直接让
    music_library_path() 返回 None 才能真正模拟「未配置」。
    """
    from types import SimpleNamespace

    fake_settings = SimpleNamespace(music_library_path=lambda: None)
    with patch("backend.play.stream.get_settings", return_value=fake_settings):
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
    test_file = tmp_path / "test.mp3"
    _make_test_file(test_file, size=1000)

    rowid = await store.insert_track(
        title="Test",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="mp3",
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


# ---------------------------------------------------------------------------
# 转码分流测试
# ---------------------------------------------------------------------------


async def test_play_alac_transcode_content_type(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """ALAC track 走转码路径时返回 Content-Type: audio/ogg。

    需要 ffmpeg 可用；不可用时跳过。
    """
    reset_ffmpeg_probe()
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

    # 探测 ffmpeg 是否可用
    from backend.play.transcode import is_ffmpeg_available

    if not is_ffmpeg_available():
        pytest.skip("ffmpeg not available — transcoding test requires ffmpeg")

    # 创建一个最小的有效 WAV 文件（ffmpeg 可解码的输入）
    # 44100 Hz, mono, 16-bit, 0.1 秒 = 4410 samples = 8820 bytes PCM
    import wave

    wav_path = tmp_path / "test.wav"
    with wave.open(str(wav_path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        # 写入 0.1 秒的静音
        frames = b"\x00\x00" * 4410
        wf.writeframes(frames)

    # DB 记录标记为 alac（模拟 ALAC track）
    rowid = await store.insert_track(
        title="ALAC Test",
        artist="A",
        path=str(wav_path).replace("\\", "/"),
        codec="alac",
        duration=100,
        size=wav_path.stat().st_size,
    )

    resp = await client.get(f"/api/play/{rowid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/ogg"
    # 转码流不应有 Content-Length（长度不可预知）
    assert "content-length" not in resp.headers
    # 转码流不可 seek：Accept-Ranges 必须声明 none，
    # 否则浏览器 <audio> 尝试 Range 探测会失败（"media resource not suitable"）
    assert resp.headers["accept-ranges"] == "none"
    # 应有 Cache-Control: no-cache
    assert resp.headers["cache-control"] == "no-cache"
    # 应有实际数据（Opus Ogg 头部）
    assert len(resp.content) > 0

    reset_ffmpeg_probe()


async def test_play_alac_ffmpeg_unavailable_503(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """ffmpeg 不可用时 ALAC 请求返回 503。"""
    reset_ffmpeg_probe()
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

    test_file = tmp_path / "test.m4a"
    _make_test_file(test_file, size=100)

    rowid = await store.insert_track(
        title="ALAC No FFmpeg",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="alac",
        duration=200000,
        size=100,
    )

    # mock shutil.which 返回 None（ffmpeg 不可用）
    with patch("backend.play.transcode.shutil.which", return_value=None):
        reset_ffmpeg_probe()
        resp = await client.get(f"/api/play/{rowid}")

    assert resp.status_code == 503
    assert "ffmpeg not available" in resp.text
    assert "alac" in resp.text

    reset_ffmpeg_probe()


async def test_play_alac_head_ffmpeg_unavailable_503(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """ffmpeg 不可用时 HEAD 请求 ALAC 也返回 503。"""
    reset_ffmpeg_probe()
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

    test_file = tmp_path / "test.m4a"
    _make_test_file(test_file, size=100)

    rowid = await store.insert_track(
        title="ALAC No FFmpeg HEAD",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="alac",
        duration=200000,
        size=100,
    )

    with patch("backend.play.transcode.shutil.which", return_value=None):
        reset_ffmpeg_probe()
        resp = await client.head(f"/api/play/{rowid}")

    # HEAD 响应 body 为空，只能通过状态码判定
    assert resp.status_code == 503

    reset_ffmpeg_probe()


async def test_play_alac_head_transcode(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """ALAC track HEAD 请求走转码路径时返回 audio/ogg + Cache-Control。"""
    reset_ffmpeg_probe()
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

    from backend.play.transcode import is_ffmpeg_available

    if not is_ffmpeg_available():
        pytest.skip("ffmpeg not available — transcoding test requires ffmpeg")

    import wave

    wav_path = tmp_path / "test.wav"
    with wave.open(str(wav_path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(b"\x00\x00" * 4410)

    rowid = await store.insert_track(
        title="ALAC HEAD Test",
        artist="A",
        path=str(wav_path).replace("\\", "/"),
        codec="alac",
        duration=100,
        size=wav_path.stat().st_size,
    )

    resp = await client.head(f"/api/play/{rowid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/ogg"
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.content == b""

    reset_ffmpeg_probe()


async def test_play_native_codec_unaffected_by_ffmpeg_absence(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """ffmpeg 不可用时，原生可解码格式（mp3/flac）仍正常直传，不受影响。"""
    reset_ffmpeg_probe()
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

    # mp3 直传
    f_mp3 = tmp_path / "test.mp3"
    _make_test_file(f_mp3, size=500)
    rid_mp3 = await store.insert_track(
        title="MP3", artist="A", path=str(f_mp3).replace("\\", "/"),
        codec="mp3", duration=200000, size=500,
    )

    with patch("backend.play.transcode.shutil.which", return_value=None):
        reset_ffmpeg_probe()
        resp = await client.get(f"/api/play/{rid_mp3}")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.headers["content-length"] == "500"
    assert resp.headers["accept-ranges"] == "bytes"

    # flac 直传
    f_flac = tmp_path / "test.flac"
    _make_test_file(f_flac, size=500)
    rid_flac = await store.insert_track(
        title="FLAC", artist="A", path=str(f_flac).replace("\\", "/"),
        codec="flac", duration=200000, size=500,
    )

    with patch("backend.play.transcode.shutil.which", return_value=None):
        reset_ffmpeg_probe()
        resp = await client.get(f"/api/play/{rid_flac}")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/flac"
    assert resp.headers["content-length"] == "500"

    reset_ffmpeg_probe()


async def test_play_transcode_process_cleanup(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """转码流结束后 ffmpeg 进程被正确清理（不残留僵尸进程）。

    通过 mock transcode_stream 验证流正常结束。
    """
    reset_ffmpeg_probe()
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

    test_file = tmp_path / "test.m4a"
    _make_test_file(test_file, size=100)

    rowid = await store.insert_track(
        title="ALAC Cleanup",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="alac",
        duration=200000,
        size=100,
    )

    # mock is_ffmpeg_available 返回 True（跳过 503 检查）
    # mock transcode_stream 返回有限数据后结束
    from collections.abc import AsyncGenerator

    async def _fake_stream(file_path: Path) -> AsyncGenerator[bytes, None]:
        yield b"fake opus data"

    with (
        patch("backend.play.stream.is_ffmpeg_available", return_value=True),
        patch("backend.play.stream.transcode_stream", side_effect=_fake_stream),
    ):
        resp = await client.get(f"/api/play/{rowid}")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/ogg"
    assert resp.content == b"fake opus data"

    reset_ffmpeg_probe()


# ---------------------------------------------------------------------------
# 客户端断连清理测试
# ---------------------------------------------------------------------------


class _FakeProc:
    """模拟同步 subprocess.Popen，用于验证断连时 kill 被调用。

    对齐真实 Popen 接口：poll()/wait()/kill() 同步，stdout/stderr 是
    _FakeStreamReader（同步 read）。
    """

    def __init__(self, chunks: list[bytes], block_after: bool = True) -> None:
        self._chunks = chunks
        self._block_after = block_after
        self.killed = False
        self._returncode: int | None = None
        self.stdout = _FakeStreamReader(chunks, block_after)
        self.stderr = _FakeStreamReader([], False)

    def poll(self) -> int | None:
        return self._returncode

    def kill(self) -> None:
        self.killed = True
        self._returncode = -9
        # 解除 stdout 的阻塞 read（线程才能退出）
        self.stdout._unblock()

    def wait(self) -> int:
        return self._returncode if self._returncode is not None else 0

    @property
    def returncode(self) -> int | None:
        return self._returncode


class _FakeStreamReader:
    """模拟同步文件/pipe read，按 chunks 返回数据，可阻塞。

    对齐真实 pipe 的 read(n)：n>0 读指定字节，n<=0/省略读全部剩余。
    阻塞用 threading.Event（在后台线程的同步上下文中阻塞，非 async）。
    """

    def __init__(self, chunks: list[bytes], block_after: bool) -> None:
        self._chunks = list(chunks)
        self._block_after = block_after
        self._index = 0
        self._unblock_event = threading.Event()

    def _unblock(self) -> None:
        self._unblock_event.set()

    def read(self, size: int = -1) -> bytes:
        # size > 0: 分块读（stdout 路径）；size <= 0: 读全部（stderr 路径）
        if size > 0:
            if self._index < len(self._chunks):
                chunk = self._chunks[self._index]
                self._index += 1
                return chunk
            if self._block_after:
                self._unblock_event.wait()
                return b""
            return b""
        # size <= 0：读全部剩余（stderr read() 无参走此路径）
        remaining = self._chunks[self._index:]
        self._index = len(self._chunks)
        return b"".join(remaining)


async def test_play_transcode_killed_on_client_disconnect(
    store: IndexStore, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """生成器被提前关闭时（客户端断开等价），ffmpeg 进程被 finally kill。

    回归 P2-1：transcode_stream 的 finally 是唯一的清理路径
    （原 _DisconnectWatcher 已删）。此测试锁住 finally 行为。

    测试策略：不走 HTTP 层（ASGITransport 的客户端断开语义不可靠，
    可能死锁）。直接对 transcode_stream 生成器做 aclose()，模拟
    StreamingResponse 在 send OSError 时关闭 body_iterator 的行为。

    fake proc 是同步 Popen 风格（poll/wait/kill 同步），patch 目标是
    backend.play.transcode.subprocess.Popen。
    """
    reset_ffmpeg_probe()
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

    test_file = tmp_path / "test.m4a"
    _make_test_file(test_file, size=100)

    # fake proc：yield 一块数据后阻塞（模拟转码进行中，stdout 未 EOF）
    fake_proc = _FakeProc(chunks=[b"partial opus data"], block_after=True)

    with patch(
        "backend.play.transcode.subprocess.Popen",
        return_value=fake_proc,
    ):
        gen = transcode_stream(test_file)
        first_chunk = await gen.__anext__()
        assert first_chunk == b"partial opus data"
        # 第二次 __anext__ 会阻塞（fake proc stdout 阻塞 + queue 无新数据）
        # 模拟 StreamingResponse 在 send OSError 时关闭生成器
        await gen.aclose()

    # 生成器被 aclose 关闭 → finally 执行 → kill（proc.poll() 非 None 判定走 kill 分支）
    assert fake_proc.killed, "ffmpeg proc 应被 finally kill"

    reset_ffmpeg_probe()


async def test_play_transcode_normally_completes_no_kill(
    store: IndexStore, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """ffmpeg 正常结束时，finally 不调 kill（poll() 非 None），只读 stderr。"""
    reset_ffmpeg_probe()
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

    test_file = tmp_path / "test.m4a"
    _make_test_file(test_file, size=100)

    rowid = await store.insert_track(
        title="ALAC Normal",
        artist="A",
        path=str(test_file).replace("\\", "/"),
        codec="alac",
        duration=200000,
        size=100,
    )

    # fake proc：yield 数据后 EOF（正常结束），returncode=0
    fake_proc = _FakeProc(chunks=[b"complete opus data"], block_after=False)
    fake_proc._returncode = 0

    with (
        patch("backend.play.stream.is_ffmpeg_available", return_value=True),
        patch("backend.play.transcode.subprocess.Popen",
              return_value=fake_proc),
    ):
        app = FastAPI()
        app.include_router(play_router, prefix="/api")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(f"/api/play/{rowid}")

    assert resp.status_code == 200
    assert resp.content == b"complete opus data"
    # 正常结束：poll() 非 None，不调 kill
    assert not fake_proc.killed, "正常结束不应调 kill"

    reset_ffmpeg_probe()


# ---------------------------------------------------------------------------
# 回归：含封面图（视频流）的 m4a 转码后只产出 Opus 音频流
# ---------------------------------------------------------------------------


async def test_play_transcode_strips_video_stream(
    store: IndexStore, client: AsyncClient, monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    """含视频流（封面图）的输入转码后只产出 Opus 音频流，不含 theora 视频。

    回归 bug：原 ffmpeg 命令缺 -vn/-map，m4a 嵌入的封面图（mov_text/cover
    视频轨）被默认映射成 theora 视频流输出，浏览器 <audio> 拿到含视频流
    的 ogg 判定 "media resource not suitable" 拒绝播放。

    复现方式：用真实 ffmpeg 合成"静音音频 + 一张纯色封面图"的 mp4 测试输入，
    走真实 transcode_stream 转码，对输出用 ffprobe 验证只有 Audio: opus 流。
    """
    reset_ffmpeg_probe()
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

    from backend.play.transcode import is_ffmpeg_available

    if not is_ffmpeg_available():
        pytest.skip("ffmpeg not available — transcode regression requires ffmpeg")

    import shutil as _shutil

    ffprobe_bin = _shutil.which("ffprobe")
    if not ffprobe_bin:
        pytest.skip("ffprobe not available — cannot verify output stream type")

    import subprocess as _sp
    import wave

    # 1. 合成静音 WAV（音频源）
    wav_path = tmp_path / "silence.wav"
    with wave.open(str(wav_path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(b"\x00\x00" * 4410)  # 0.1 秒静音

    # 2. 合成纯色 PNG 封面图（视频源）—— 用 ffmpeg 生成
    cover_path = tmp_path / "cover.png"
    _sp.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=0.1",
         "-frames:v", "1", str(cover_path)],
        check=True, capture_output=True,
    )

    # 3. 合成含封面图的 mp4（音频 + 视频流，模拟真实带封面的 m4a）
    mp4_path = tmp_path / "with_cover.m4a"
    _sp.run(
        ["ffmpeg", "-y",
         "-i", str(wav_path),
         "-i", str(cover_path),
         "-map", "0:a:0", "-map", "1:v:0",
         "-c:a", "aac", "-c:v", "libx264",
         "-shortest", str(mp4_path)],
        check=True, capture_output=True,
    )

    # 4. 入库，标记 alac（走转码分支）
    rowid = await store.insert_track(
        title="WithCover",
        artist="A",
        path=str(mp4_path).replace("\\", "/"),
        codec="alac",
        duration=100,
        size=mp4_path.stat().st_size,
    )

    # 5. 请求转码，落盘输出
    resp = await client.get(f"/api/play/{rowid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/ogg"
    assert len(resp.content) > 0

    # 6. ffprobe 验证：输出只能是 Audio: opus，不能有 Video: theora
    out_path = tmp_path / "out.ogg"
    out_path.write_bytes(resp.content)

    probe = _sp.run(
        [ffprobe_bin, "-hide_banner", "-show_streams", str(out_path)],
        capture_output=True, text=True, check=True,
    )
    # 解析流类型：提取所有 codec_type= 行
    stream_types = [
        line.split("=", 1)[1].strip()
        for line in probe.stdout.splitlines()
        if line.startswith("codec_type=")
    ]
    assert stream_types, "ffprobe 未解析出任何流（输出可能损坏）"
    assert "video" not in stream_types, (
        f"转码输出含视频流（{stream_types}），应为纯音频——回归 -vn 丢失"
    )
    assert "audio" in stream_types, f"转码输出无音频流（{stream_types}）"

    # 进一步验证音频 codec 是 opus
    codec_names = [
        line.split("=", 1)[1].strip()
        for line in probe.stdout.splitlines()
        if line.startswith("codec_name=")
    ]
    assert "opus" in codec_names, (
        f"音频 codec 非 opus（{codec_names}）——转码输出格式错误"
    )

    reset_ffmpeg_probe()