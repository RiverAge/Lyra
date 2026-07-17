"""测试——歌词 sidecar 读写 + lyrics_sidecar_routes。

覆盖：
- 路径计算：三来源（apple/netease/qq）正确 + ``-后缀`` 命名
- 深层目录镜像（多级 Artist/Album/）
- 越界回退（恶意 ``../`` 路径 → is_within_lyrics_root False）
- read/write/delete round-trip（临时目录）
- list_sidecars：apple + netease(ttml+raw) + qq 共存
- 路由：GET 列表 / GET 单个 / DELETE / POST / 404 / 路径越界 404
- planned_lyrics_paths：-后缀命名 + doubled-source 断言
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.index.store import IndexStore, set_store
from backend.lyrics.sidecar import (
    delete_sidecar,
    is_within_lyrics_root,
    list_sidecars,
    mirror_relative_path,
    planned_lyrics_paths,
    read_sidecar,
    sidecar_path_for,
    write_sidecar,
)
from backend.server.lyrics_sidecar_routes import lyrics_sidecar_router

# asyncio_mode = "auto" 由 pyproject.toml 设定


# ---------------------------------------------------------------------------
# 路径计算测试
# ---------------------------------------------------------------------------


class TestPathCalc:
    """sidecar 路径算法测试（照搬 lyrics_io.py 的纯函数 + Lyra 封装）。"""

    def test_three_sources_paths(self, tmp_path: Path) -> None:
        """三来源路径正确 + -后缀命名。"""
        library = tmp_path / "library"
        audio = library / "apple" / "Artist" / "Album" / "01 Song.m4a"
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"\x00")

        apple_path = sidecar_path_for(audio, library, "apple")
        netease_path = sidecar_path_for(audio, library, "netease")
        qq_path = sidecar_path_for(audio, library, "qq")

        # apple 默认词：<song>.ttml（无后缀）
        assert apple_path == library / ".lyrics" / "apple" / "Artist" / "Album" / "01 Song.ttml"
        # netease 增强词：<song>-netease.ttml（平铺在 apple/ 同目录）
        assert netease_path == (
            library / ".lyrics" / "apple" / "Artist" / "Album" / "01 Song-netease.ttml"
        )
        # qq 增强词：<song>-qq.ttml（平铺在 apple/ 同目录）
        assert qq_path == (
            library / ".lyrics" / "apple" / "Artist" / "Album" / "01 Song-qq.ttml"
        )

    def test_deep_directory_mirror(self, tmp_path: Path) -> None:
        """深层目录镜像：多级 Artist/Album/DiscN 路径完整镜像。"""
        library = tmp_path / "lib"
        audio = library / "apple" / "周杰" / "范特西" / "Disc 1" / "01 晴天.m4a"
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"\x00")

        apple_path = sidecar_path_for(audio, library, "apple")
        netease_path = sidecar_path_for(audio, library, "netease")

        assert apple_path == (
            library / ".lyrics" / "apple" / "周杰" / "范特西" / "Disc 1" / "01 晴天.ttml"
        )
        assert netease_path == (
            library / ".lyrics" / "apple" / "周杰" / "范特西" / "Disc 1"
            / "01 晴天-netease.ttml"
        )

    def test_planned_lyrics_paths_suffix_naming(self, tmp_path: Path) -> None:
        """planned_lyrics_paths（参考源副本）的 -后缀命名 + 前置 source 段语义。

        这是照搬参考源 lyrics_io.py 的纯函数副本（签名一致，供 M5-A 合流收敛），
        其语义是「source 段前置到完整 mirror 前」——与 Lyra sidecar_path_for 的
        「source 替换 mirror 首段」不同。这里断言副本与参考源一致：
        audio=apple/A/B/song.m4a → am_ttml=apple/apple/A/B/song.ttml（双 apple）。
        -后缀命名（-netease/-qq）是本函数的核心契约，与 AGENTS.md §3.3 一致。
        """
        library = tmp_path / "lib"
        lyrics_root = library / ".lyrics"
        audio = library / "apple" / "A" / "B" / "song.m4a"
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"\x00")

        # netease：source=netease 前置，suffix=-netease
        paths = planned_lyrics_paths(
            audio, library, lyrics_root, ttml_source="netease", lyric_source_suffix="netease",
        )
        assert Path(paths["am_ttml_path"]).as_posix().endswith("apple/apple/A/B/song.ttml")
        assert Path(paths["netease_ttml_path"]).as_posix().endswith(
            "netease/apple/A/B/song-netease.ttml",
        )
        assert Path(paths["netease_raw_path"]).as_posix().endswith(
            "netease/apple/A/B/song.json",
        )

        # qq：source=qq 前置，suffix=-qq
        paths_qq = planned_lyrics_paths(
            audio, library, lyrics_root, ttml_source="qq", lyric_source_suffix="qq",
        )
        assert Path(paths_qq["qq_ttml_path"]).as_posix().endswith("qq/apple/A/B/song-qq.ttml")
        assert Path(paths_qq["qq_raw_path"]).as_posix().endswith("qq/apple/A/B/song.json")

    def test_sidecar_path_for_flat_in_apple_dir(self, tmp_path: Path) -> None:
        """sidecar_path_for（Lyra 封装）：所有来源平铺在 .lyrics/apple/ 下，靠后缀区分。

        对齐 navidrome lyric-bridge：bridge 在 .lyrics/<音频镜像目录> 一个目录里
        扫 <song>.ttml / <song>-netease.ttml / <song>-qq.ttml。故三来源 sidecar
        必须落在同一目录（.lyrics/apple/Artist/Album/），source 只进文件名后缀。
        apple 无后缀，netease/qq 加 -<source> 后缀。这是 Lyra 侧实际落盘契约。
        """
        library = tmp_path / "lib"
        audio = library / "apple" / "Artist" / "Album" / "01 Song.m4a"
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"\x00")

        assert sidecar_path_for(audio, library, "apple") == (
            library / ".lyrics" / "apple" / "Artist" / "Album" / "01 Song.ttml"
        )
        assert sidecar_path_for(audio, library, "netease") == (
            library / ".lyrics" / "apple" / "Artist" / "Album" / "01 Song-netease.ttml"
        )
        assert sidecar_path_for(audio, library, "qq") == (
            library / ".lyrics" / "apple" / "Artist" / "Album" / "01 Song-qq.ttml"
        )
        from backend.lyrics.sidecar import raw_json_path_for
        assert raw_json_path_for(audio, library, "netease") == (
            library / ".lyrics" / "apple" / "Artist" / "Album" / "01 Song.json"
        )
        assert raw_json_path_for(audio, library, "apple") is None
        assert raw_json_path_for(audio, library, "qq") is None

    def test_planned_lyrics_paths_doubled_source_assertion(self, tmp_path: Path) -> None:
        """_assert_no_doubled_source_segment：mirror 含 source 段时报错。"""
        library = tmp_path / "lib"
        lyrics_root = library / ".lyrics"
        # 构造 audio 路径使 mirror_relative_path 以 "common" 开头
        audio = library / "common" / "Artist" / "song.m4a"
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"\x00")

        with pytest.raises(ValueError, match="doubled source segment"):
            planned_lyrics_paths(
                audio, library, lyrics_root,
                ttml_source="common", lyric_source_suffix="common",
            )

    def test_mirror_relative_path_outside_root(self, tmp_path: Path) -> None:
        """mirror_relative_path：path 不在 root 下 → 退化为文件名。"""
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "elsewhere" / "song.m4a"
        rel = mirror_relative_path(outside, root)
        assert rel == Path("song.m4a")


# ---------------------------------------------------------------------------
# 路径安全测试
# ---------------------------------------------------------------------------


class TestPathSafety:
    """路径安全：防 ../ 越出 .lyrics/。"""

    def test_normal_path_within_root(self, tmp_path: Path) -> None:
        """正常 sidecar 路径 → is_within_lyrics_root True。"""
        library = tmp_path / "lib"
        audio = library / "apple" / "A" / "song.m4a"
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"\x00")
        path = sidecar_path_for(audio, library, "netease")
        assert is_within_lyrics_root(path, library) is True

    def test_malicious_traversal_rejected(self, tmp_path: Path) -> None:
        """恶意 ../ 路径 → is_within_lyrics_root False。

        构造一个明显越出 .lyrics/ 的路径，断言被拒。
        """
        library = tmp_path / "lib"
        library.mkdir()
        lyrics_root = library / ".lyrics"
        lyrics_root.mkdir()
        # 构造越界路径：.lyrics/../../etc/passwd
        malicious = lyrics_root / ".." / ".." / "etc" / "passwd"
        assert is_within_lyrics_root(malicious, library) is False

    def test_malicious_traversal_resolves_outside(self, tmp_path: Path) -> None:
        """resolve() 后落在 .lyrics/ 之外 → False（resolve + is_relative_to 生效）。"""
        library = tmp_path / "lib"
        library.mkdir()
        lyrics_root = library / ".lyrics"
        lyrics_root.mkdir()
        # .lyrics/../secret.ttml → resolve 到 library/secret.ttml（不在 .lyrics 下）
        sneaky = lyrics_root / ".." / "secret.ttml"
        assert is_within_lyrics_root(sneaky, library) is False


# ---------------------------------------------------------------------------
# TTML/JSON CRUD round-trip 测试
# ---------------------------------------------------------------------------


class TestSidecarCRUD:
    """read/write/delete round-trip（临时目录）。"""

    def test_write_then_read_roundtrip(self, tmp_path: Path) -> None:
        """写 → 读：内容一致。"""
        path = tmp_path / "deep" / "nested" / "song.ttml"
        content = "<tt xml:lang=\"zh\">hello</tt>"
        write_sidecar(path, content)
        assert read_sidecar(path) == content

    def test_read_nonexistent_returns_none(self, tmp_path: Path) -> None:
        """读不存在的文件 → None。"""
        path = tmp_path / "nope.ttml"
        assert read_sidecar(path) is None

    def test_delete_existing(self, tmp_path: Path) -> None:
        """删除存在的文件 → True，删后文件不存在。"""
        path = tmp_path / "song.ttml"
        write_sidecar(path, "x")
        assert delete_sidecar(path) is True
        assert not path.is_file()

    def test_delete_nonexistent_returns_false(self, tmp_path: Path) -> None:
        """删除不存在的文件 → False（幂等）。"""
        path = tmp_path / "nope.ttml"
        assert delete_sidecar(path) is False

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        """写操作自动创建深层父目录。"""
        path = tmp_path / "a" / "b" / "c" / "d" / "song.ttml"
        write_sidecar(path, "content")
        assert path.is_file()


# ---------------------------------------------------------------------------
# list_sidecars 测试
# ---------------------------------------------------------------------------


class TestListSidecars:
    """list_sidecars：多来源共存 + raw json。"""

    def test_list_empty_when_no_sidecars(self, tmp_path: Path) -> None:
        """无任何 sidecar → 空列表。"""
        library = tmp_path / "lib"
        audio = library / "apple" / "A" / "song.m4a"
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"\x00")
        assert list_sidecars(audio, library) == []

    def test_list_all_sources_coexist(self, tmp_path: Path) -> None:
        """apple + netease(ttml+raw) + qq 共存 → 列表含 4 条。"""
        library = tmp_path / "lib"
        audio = library / "apple" / "A" / "song.m4a"
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"\x00")

        apple_path = sidecar_path_for(audio, library, "apple")
        netease_path = sidecar_path_for(audio, library, "netease")
        qq_path = sidecar_path_for(audio, library, "qq")
        from backend.lyrics.sidecar import raw_json_path_for
        raw_path = raw_json_path_for(audio, library, "netease")

        write_sidecar(apple_path, "<tt>apple</tt>")
        write_sidecar(netease_path, "<tt>netease</tt>")
        write_sidecar(qq_path, "<tt>qq</tt>")
        assert raw_path is not None
        write_sidecar(raw_path, '{"lyric": "raw"}')

        sidecars = list_sidecars(audio, library)
        # 4 条：apple ttml + netease ttml + netease json + qq ttml
        assert len(sidecars) == 4
        sources_formats = {(s["source"], s["format"]) for s in sidecars}
        assert ("apple", "ttml") in sources_formats
        assert ("netease", "ttml") in sources_formats
        assert ("netease", "json") in sources_formats
        assert ("qq", "ttml") in sources_formats

    def test_list_partial_sources(self, tmp_path: Path) -> None:
        """仅 apple 存在 → 列表只含 1 条。"""
        library = tmp_path / "lib"
        audio = library / "apple" / "A" / "song.m4a"
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"\x00")

        apple_path = sidecar_path_for(audio, library, "apple")
        write_sidecar(apple_path, "<tt>apple</tt>")

        sidecars = list_sidecars(audio, library)
        assert len(sidecars) == 1
        assert sidecars[0]["source"] == "apple"
        assert sidecars[0]["content"] == "<tt>apple</tt>"


# ---------------------------------------------------------------------------
# 路由测试 — fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """创建含 lyrics_sidecar_router 的测试 app。"""
    app_fast = FastAPI()
    app_fast.include_router(lyrics_sidecar_router, prefix="/api")
    return app_fast


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """返回已绑定测试 app 的 httpx AsyncClient。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _prepare_track(
    store: IndexStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    title: str = "Test Song",
) -> int:
    """辅助：创建测试音频文件并插入 store，返回 rowid。"""
    monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

    audio = tmp_path / "apple" / "Artist" / "Album" / "01 Song.m4a"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"\x00" * 100)

    return await store.insert_track(
        title=title,
        artist="Artist",
        path=str(audio).replace("\\", "/"),
        codec="alac",
        duration=200000,
    )


# ---------------------------------------------------------------------------
# 路由测试
# ---------------------------------------------------------------------------


class TestSidecarRoutes:
    """lyrics_sidecar_routes 端点测试。"""

    async def test_get_sidecars_list(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """GET /sidecars → 200 + sidecars 列表。"""
        rowid = await _prepare_track(store, tmp_path, monkeypatch)

        # 预先写两个 sidecar
        library = tmp_path
        audio = library / "apple" / "Artist" / "Album" / "01 Song.m4a"
        apple_path = sidecar_path_for(audio, library, "apple")
        netease_path = sidecar_path_for(audio, library, "netease")
        write_sidecar(apple_path, "<tt>apple</tt>")
        write_sidecar(netease_path, "<tt>netease</tt>")

        resp = await client.get(f"/api/lyrics/{rowid}/sidecars")
        assert resp.status_code == 200
        body = resp.json()
        assert body["track_id"] == str(rowid)
        assert len(body["sidecars"]) == 2
        sources = {s["source"] for s in body["sidecars"]}
        assert "apple" in sources
        assert "netease" in sources

    async def test_get_sidecars_empty(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """无 sidecar → 200 + 空列表。"""
        rowid = await _prepare_track(store, tmp_path, monkeypatch)
        resp = await client.get(f"/api/lyrics/{rowid}/sidecars")
        assert resp.status_code == 200
        assert resp.json()["sidecars"] == []

    async def test_get_single_sidecar(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """GET /sidecar/apple → 200 + content。"""
        rowid = await _prepare_track(store, tmp_path, monkeypatch)
        library = tmp_path
        audio = library / "apple" / "Artist" / "Album" / "01 Song.m4a"
        apple_path = sidecar_path_for(audio, library, "apple")
        write_sidecar(apple_path, "<tt>apple lyrics</tt>")

        resp = await client.get(f"/api/lyrics/{rowid}/sidecar/apple")
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "apple"
        assert body["format"] == "ttml"
        assert body["content"] == "<tt>apple lyrics</tt>"

    async def test_get_single_sidecar_not_found(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """sidecar 不存在 → 404。"""
        rowid = await _prepare_track(store, tmp_path, monkeypatch)
        resp = await client.get(f"/api/lyrics/{rowid}/sidecar/netease")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_get_sidecar_invalid_source(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """非法 source → 404。"""
        rowid = await _prepare_track(store, tmp_path, monkeypatch)
        resp = await client.get(f"/api/lyrics/{rowid}/sidecar/spotify")
        assert resp.status_code == 404
        assert "unknown" in resp.json()["detail"].lower()

    async def test_post_sidecar_write(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """POST /sidecar/netease → 200 + written + 文件落盘 + 内容正确。"""
        rowid = await _prepare_track(store, tmp_path, monkeypatch)
        ttml_content = "<tt xml:lang=\"zh\"><div>手动写入</div></tt>"

        resp = await client.post(
            f"/api/lyrics/{rowid}/sidecar/netease",
            json={"content": ttml_content},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["written"] is True
        assert body["source"] == "netease"

        # 验证文件落盘
        library = tmp_path
        audio = library / "apple" / "Artist" / "Album" / "01 Song.m4a"
        netease_path = sidecar_path_for(audio, library, "netease")
        assert netease_path.is_file()
        assert netease_path.read_text(encoding="utf-8") == ttml_content
        # -后缀命名正确
        assert netease_path.name == "01 Song-netease.ttml"

    async def test_delete_sidecar(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """DELETE /sidecar/qq → 200 + deleted=true + 文件删除。"""
        rowid = await _prepare_track(store, tmp_path, monkeypatch)
        library = tmp_path
        audio = library / "apple" / "Artist" / "Album" / "01 Song.m4a"
        qq_path = sidecar_path_for(audio, library, "qq")
        write_sidecar(qq_path, "<tt>qq</tt>")
        assert qq_path.is_file()

        resp = await client.delete(f"/api/lyrics/{rowid}/sidecar/qq")
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted"] is True
        assert not qq_path.is_file()

    async def test_delete_sidecar_idempotent(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """删除不存在的 sidecar → 200 + deleted=false（幂等）。"""
        rowid = await _prepare_track(store, tmp_path, monkeypatch)
        resp = await client.delete(f"/api/lyrics/{rowid}/sidecar/qq")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is False

    async def test_post_then_get_roundtrip(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """POST 写入 → GET 读回 → 内容一致。"""
        rowid = await _prepare_track(store, tmp_path, monkeypatch)
        ttml = "<tt>roundtrip</tt>"

        resp_post = await client.post(
            f"/api/lyrics/{rowid}/sidecar/apple",
            json={"content": ttml},
        )
        assert resp_post.status_code == 200

        resp_get = await client.get(f"/api/lyrics/{rowid}/sidecar/apple")
        assert resp_get.status_code == 200
        assert resp_get.json()["content"] == ttml

    async def test_track_not_found(
        self,
        store: IndexStore,
        client: AsyncClient,
    ) -> None:
        """不存在的 track_id → 404。"""
        resp = await client.get("/api/lyrics/999999/sidecars")
        assert resp.status_code == 404

    async def test_invalid_track_id(
        self,
        client: AsyncClient,
    ) -> None:
        """非数字 track_id → 422。"""
        resp = await client.get("/api/lyrics/abc/sidecars")
        assert resp.status_code == 422

    async def test_db_unavailable(self, app: FastAPI) -> None:
        """store 未初始化 → 503。"""
        set_store(None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/lyrics/1/sidecars")
            assert resp.status_code == 503
            assert "Database not initialized" in resp.text

    async def test_path_traversal_track(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """track 路径不在 library_root 下 → 404（_resolve_track 拦截）。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

        rowid = await store.insert_track(
            title="Outside",
            artist="A",
            path="/some/other/path/file.m4a",
            codec="alac",
            duration=200000,
        )

        resp = await client.get(f"/api/lyrics/{rowid}/sidecars")
        assert resp.status_code == 404

    async def test_file_not_exists(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """DB 有记录但音频文件不存在 → 404。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

        rowid = await store.insert_track(
            title="Ghost",
            artist="A",
            path=str(tmp_path / "nonexistent.m4a").replace("\\", "/"),
            codec="alac",
            duration=200000,
        )

        resp = await client.get(f"/api/lyrics/{rowid}/sidecars")
        assert resp.status_code == 404
