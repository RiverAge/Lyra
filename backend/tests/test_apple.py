"""测试——Apple WebAPI 客户端 + apple_routes。

覆盖：
- TokenManager：JWT exp 解码、过期判定、并发去重
- get_song_info：mock httpx 响应 → authoritative_fields 字段对齐 FIELD_MAP
- 401 被动刷新：mock 第一次 401 → 刷新 → 第二次 200
- Apple 404 → AppleAPIError
- route GET /api/meta/{id}/apple：200 + authoritative_fields
- song_id 缺失 → 400；track 不存在 → 404；store 未初始化 → 503
- 非数字 track_id → 422
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.index.store import IndexStore, set_store
from backend.meta.apple import (
    AppleAPIError,
    TokenManager,
    _decode_jwt_exp,
    _map_song_attributes,
    get_album_info,
    get_song_info,
)
from backend.server.apple_routes import apple_router

# asyncio_mode = "auto" 由 pyproject.toml 设定


# ---------------------------------------------------------------------------
# 辅助：构造 mock JWT
# ---------------------------------------------------------------------------


def _make_jwt(exp: int, payload_extra: dict[str, object] | None = None) -> str:
    """构造一个 mock JWT，payload 含 exp 字段。

    Returns:
        三段式 JWT 字符串（header.payload.signature）
    """
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "ES256", "typ": "JWT"}).encode(),
    ).rstrip(b"=").decode()

    payload_dict: dict[str, object] = {"exp": exp}
    if payload_extra:
        payload_dict.update(payload_extra)
    payload = base64.urlsafe_b64encode(
        json.dumps(payload_dict).encode(),
    ).rstrip(b"=").decode()

    signature = base64.urlsafe_b64encode(b"fake_sig").rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


# ---------------------------------------------------------------------------
# 辅助：构造 Apple API song 响应
# ---------------------------------------------------------------------------


def _make_song_response(
    song_id: str = "1234567890",
    name: str = "Test Song",
    artist_name: str = "Test Artist",
    album_name: str = "Test Album",
    composer_name: str = "Test Composer",
    genre_names: list[str] | None = None,
    isrc: str = "USXXX1234567",
    release_date: str = "2024-01-15",
    track_number: int = 1,
    disc_number: int = 1,
    duration_ms: int = 240000,
    album_artist: str = "Album Artist",
    copyright_val: str = "© 2024 Test Label",
    record_label: str = "Test Records",
    upc: str = "1234567890123",
) -> dict[str, object]:
    """构造 Apple amp-api songs 响应 dict。"""
    if genre_names is None:
        genre_names = ["Pop", "Rock"]
    return {
        "data": [
            {
                "id": song_id,
                "type": "songs",
                "href": f"/v1/catalog/us/songs/{song_id}",
                "attributes": {
                    "name": name,
                    "artistName": artist_name,
                    "albumName": album_name,
                    "composerName": composer_name,
                    "genreNames": genre_names,
                    "isrc": isrc,
                    "releaseDate": release_date,
                    "trackNumber": track_number,
                    "discNumber": disc_number,
                    "durationInMillis": duration_ms,
                    "hasLyrics": True,
                    "hasTimeSyncedLyrics": False,
                    "hasCredits": True,
                    "isAppleDigitalMaster": True,
                    "isMasteredForItunes": False,
                    "contentRating": "explicit",
                    "audioTraits": ["atmos", "hi-res-lossless"],
                },
                "relationships": {
                    "albums": {
                        "href": "/v1/catalog/us/albums/123",
                        "data": [
                            {
                                "id": "123",
                                "type": "albums",
                                "attributes": {
                                    "artistName": album_artist,
                                    "copyright": copyright_val,
                                    "recordLabel": record_label,
                                    "upc": upc,
                                },
                            },
                        ],
                    },
                    "artists": {
                        "href": "/v1/catalog/us/artists/456",
                        "data": [{"id": "456", "type": "artists"}],
                    },
                },
            },
        ],
    }


# ---------------------------------------------------------------------------
# TokenManager 测试
# ---------------------------------------------------------------------------


class TestTokenManager:
    """TokenManager 单元测试。"""

    def setup_method(self) -> None:
        """每个测试前重置单例。"""
        TokenManager.reset_instance()

    def teardown_method(self) -> None:
        """每个测试后重置单例。"""
        TokenManager.reset_instance()

    def test_jwt_exp_decode(self) -> None:
        """JWT exp 解码正确。"""
        exp = int(time.time()) + 3600  # 1 小时后
        token = _make_jwt(exp)
        decoded_exp = _decode_jwt_exp(token)
        assert decoded_exp == exp

    def test_jwt_exp_decode_with_padding(self) -> None:
        """JWT payload 需补齐 base64 padding 时仍正确解码。"""
        # 构造一个 payload 长度不是 4 的倍数的 JWT
        exp = int(time.time()) + 3600
        payload_dict = {"exp": exp, "iss": "test"}  # 加额外字段改变长度
        payload_b64 = base64.urlsafe_b64encode(
            json.dumps(payload_dict).encode(),
        ).rstrip(b"=").decode()
        header_b64 = base64.urlsafe_b64encode(b'{"alg":"ES256"}').rstrip(b"=").decode()
        sig_b64 = base64.urlsafe_b64encode(b"sig").rstrip(b"=").decode()
        token = f"{header_b64}.{payload_b64}.{sig_b64}"
        decoded_exp = _decode_jwt_exp(token)
        assert decoded_exp == exp

    def test_is_valid_fresh_token(self) -> None:
        """有效 token（exp 远在未来）→ _is_valid True。"""
        tm = TokenManager.get_instance()
        exp = int(time.time()) + 3600
        tm._token = _make_jwt(exp)
        tm._token_exp = exp
        assert tm._is_valid() is True

    def test_is_valid_expired_token(self) -> None:
        """过期 token（exp 在过去）→ _is_valid False。"""
        tm = TokenManager.get_instance()
        exp = int(time.time()) - 100  # 100 秒前过期
        tm._token = _make_jwt(exp)
        tm._token_exp = exp
        assert tm._is_valid() is False

    def test_is_valid_about_to_expire(self) -> None:
        """即将过期 token（exp - 60s < now）→ _is_valid False。"""
        tm = TokenManager.get_instance()
        exp = int(time.time()) + 30  # 30 秒后过期，提前 60s 判定
        tm._token = _make_jwt(exp)
        tm._token_exp = exp
        assert tm._is_valid() is False

    def test_is_valid_no_token(self) -> None:
        """无 token → _is_valid False。"""
        tm = TokenManager.get_instance()
        assert tm._is_valid() is False

    async def test_ensure_token_skips_when_valid(self) -> None:
        """有效 token 时 ensure_token 不触发 _fetch_token。"""
        tm = TokenManager.get_instance()
        exp = int(time.time()) + 3600
        fake_token = _make_jwt(exp)
        tm._token = fake_token
        tm._token_exp = exp

        # mock _fetch_token 确保不被调用
        tm._fetch_token = AsyncMock()  # type: ignore[assignment]

        result = await tm.ensure_token()
        assert result == fake_token
        tm._fetch_token.assert_not_called()

    async def test_concurrent_ensure_token_dedup(self) -> None:
        """多协程同时 ensure_token，Lock 生效只抓一次。"""
        tm = TokenManager.get_instance()
        exp = int(time.time()) + 3600
        fake_token = _make_jwt(exp)
        fetch_count = 0

        async def mock_fetch() -> None:
            nonlocal fetch_count
            fetch_count += 1
            # 模拟网络延迟
            await asyncio.sleep(0.05)
            tm._token = fake_token
            tm._token_exp = exp

        tm._fetch_token = mock_fetch  # type: ignore[assignment]

        # 5 个协程同时 ensure_token
        results = await asyncio.gather(
            tm.ensure_token(),
            tm.ensure_token(),
            tm.ensure_token(),
            tm.ensure_token(),
            tm.ensure_token(),
        )
        # 所有结果一致
        assert all(r == fake_token for r in results)
        # _fetch_token 只被调用 1 次
        assert fetch_count == 1

    async def test_invalidate_and_refresh(self) -> None:
        """invalidate_and_refresh 清空 token 后重新获取。"""
        tm = TokenManager.get_instance()
        exp = int(time.time()) + 3600
        old_token = _make_jwt(exp)
        new_exp = int(time.time()) + 7200
        new_token = _make_jwt(new_exp)

        tm._token = old_token
        tm._token_exp = exp

        fetch_count = 0

        async def mock_fetch() -> None:
            nonlocal fetch_count
            fetch_count += 1
            tm._token = new_token
            tm._token_exp = new_exp

        tm._fetch_token = mock_fetch  # type: ignore[assignment]

        result = await tm.invalidate_and_refresh()
        assert result == new_token
        assert fetch_count == 1


# ---------------------------------------------------------------------------
# _map_song_attributes 测试
# ---------------------------------------------------------------------------


class TestMapSongAttributes:
    """_map_song_attributes 映射测试。"""

    def test_basic_field_mapping(self) -> None:
        """基本字段映射：name→title, artistName→artist 等。"""
        api_data = _make_song_response()
        result = _map_song_attributes(api_data, "1234567890")

        assert result["title"] == ["Test Song"]
        assert result["artist"] == ["Test Artist"]
        assert result["album"] == ["Test Album"]
        assert result["composer"] == ["Test Composer"]
        assert result["genre"] == ["Pop", "Rock"]
        assert result["isrc"] == ["USXXX1234567"]

    def test_album_relationship_mapping(self) -> None:
        """album relationship 字段映射：artistName→album_artist 等。"""
        api_data = _make_song_response()
        result = _map_song_attributes(api_data, "1234567890")

        assert result["album_artist"] == ["Album Artist"]
        assert result["copyright"] == ["© 2024 Test Label"]
        assert result["record_company"] == ["Test Records"]
        assert result["barcode"] == ["1234567890123"]

    def test_raw_fields_populated(self) -> None:
        """不在 FIELD_MAP 的字段放入 raw 子字典。"""
        api_data = _make_song_response()
        result = _map_song_attributes(api_data, "1234567890")

        assert "raw" in result
        raw_data = json.loads(result["raw"][0])
        assert raw_data["releaseDate"] == ["2024-01-15"]
        assert raw_data["trackNumber"] == ["1"]
        assert raw_data["discNumber"] == ["1"]
        assert raw_data["durationInMillis"] == ["240000"]
        assert raw_data["hasLyrics"] == ["True"]
        assert raw_data["audioTraits"] == ["atmos", "hi-res-lossless"]

    def test_missing_optional_fields(self) -> None:
        """可选字段缺失时不报错，不产生对应 key。"""
        api_data = _make_song_response(composer_name="", isrc="")
        # composerName 为空字符串 → 不映射
        result = _map_song_attributes(api_data, "1234567890")
        assert "composer" not in result
        assert "isrc" not in result

    def test_no_album_relationship(self) -> None:
        """无 album relationship 时不映射 album_artist/copyright 等。"""
        api_data = _make_song_response()
        # 删除 album relationship
        api_data["data"][0]["relationships"] = {}  # type: ignore[index]
        result = _map_song_attributes(api_data, "1234567890")
        assert "album_artist" not in result
        assert "copyright" not in result
        assert "record_company" not in result
        assert "barcode" not in result

    def test_song_id_not_in_response(self) -> None:
        """song_id 不在 API 响应中 → AppleAPIError。"""
        api_data = _make_song_response(song_id="999")
        with pytest.raises(AppleAPIError, match="not found in API response"):
            _map_song_attributes(api_data, "1234567890")

    def test_genre_single_string(self) -> None:
        """genreNames 为单元素列表时正确映射。"""
        api_data = _make_song_response(genre_names=["Pop"])
        result = _map_song_attributes(api_data, "1234567890")
        assert result["genre"] == ["Pop"]


# ---------------------------------------------------------------------------
# get_song_info 测试
# ---------------------------------------------------------------------------


class TestGetSongInfo:
    """get_song_info mock httpx 测试。"""

    def setup_method(self) -> None:
        TokenManager.reset_instance()

    def teardown_method(self) -> None:
        TokenManager.reset_instance()

    async def test_get_song_info_success(self) -> None:
        """mock 200 响应 → authoritative_fields 字段对齐 FIELD_MAP。"""
        # 预设 token
        tm = TokenManager.get_instance()
        exp = int(time.time()) + 3600
        tm._token = _make_jwt(exp)
        tm._token_exp = exp

        api_response = _make_song_response()

        # mock httpx.AsyncClient.get
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = api_response
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.meta.apple.httpx.AsyncClient", return_value=mock_client):
            result = await get_song_info("1234567890", "us", "zh-Hans")

        # 验证关键字段对齐 FIELD_MAP
        assert result["title"] == ["Test Song"]
        assert result["artist"] == ["Test Artist"]
        assert result["album"] == ["Test Album"]
        assert result["composer"] == ["Test Composer"]
        assert result["genre"] == ["Pop", "Rock"]
        assert result["isrc"] == ["USXXX1234567"]
        assert result["album_artist"] == ["Album Artist"]
        assert result["copyright"] == ["© 2024 Test Label"]
        assert result["record_company"] == ["Test Records"]
        assert result["barcode"] == ["1234567890123"]

    async def test_get_song_info_401_then_200(self) -> None:
        """401 被动刷新：第一次 401 → 刷新 token → 第二次 200。"""
        tm = TokenManager.get_instance()
        exp = int(time.time()) + 3600
        old_token = _make_jwt(exp)
        new_exp = int(time.time()) + 7200
        new_token = _make_jwt(new_exp)
        tm._token = old_token
        tm._token_exp = exp

        api_response = _make_song_response()

        # 第一次 401，第二次 200
        resp_401 = MagicMock()
        resp_401.status_code = 401

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = api_response
        resp_200.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[resp_401, resp_200])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        # mock invalidate_and_refresh 返回新 token
        with (
            patch("backend.meta.apple.httpx.AsyncClient", return_value=mock_client),
            patch.object(
                tm, "invalidate_and_refresh",
                new_callable=AsyncMock,
                return_value=new_token,
            ),
        ):
            result = await get_song_info("1234567890", "us", "zh-Hans")

        assert result["title"] == ["Test Song"]
        # 验证 get 被调用了 2 次（第一次 401，第二次 200）
        assert mock_client.get.call_count == 2

    async def test_get_song_info_404(self) -> None:
        """Apple API 404 → AppleAPIError。"""
        tm = TokenManager.get_instance()
        exp = int(time.time()) + 3600
        tm._token = _make_jwt(exp)
        tm._token_exp = exp

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.meta.apple.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(AppleAPIError, match="not found"):
                await get_song_info("9999999", "us", "zh-Hans")

    async def test_get_song_info_invalid_response(self) -> None:
        """API 返回 errors 或无 data → AppleAPIError。"""
        tm = TokenManager.get_instance()
        exp = int(time.time()) + 3600
        tm._token = _make_jwt(exp)
        tm._token_exp = exp

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"errors": [{"status": "404"}]}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.meta.apple.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(AppleAPIError, match="Invalid response"):
                await get_song_info("1234567890", "us", "zh-Hans")


# ---------------------------------------------------------------------------
# apple_routes 测试 — fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """创建含 apple_router 的测试 app。"""
    app_fast = FastAPI()
    app_fast.include_router(apple_router, prefix="/api")
    return app_fast


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """返回已绑定测试 app 的 httpx AsyncClient。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# apple_routes 测试
# ---------------------------------------------------------------------------


class TestAppleRoute:
    """GET /api/meta/{track_id}/apple 测试。"""

    async def test_apple_fetch_success(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """正常请求 → 200 + authoritative_fields。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

        # 创建一个假文件
        fake_file = tmp_path / "test.m4a"
        fake_file.write_bytes(b"\x00" * 100)

        # 插入 track，tag_map 含 cnID
        rowid = await store.insert_track(
            title="Test",
            artist="Artist",
            path=str(fake_file).replace("\\", "/"),
            codec="alac",
            duration=200000,
            tag_map='{"cnID": ["1234567890"]}',
        )

        # mock get_song_info
        mock_fields: dict[str, list[str]] = {
            "title": ["Apple Title"],
            "artist": ["Apple Artist"],
            "album": ["Apple Album"],
            "composer": ["Apple Composer"],
            "genre": ["Pop"],
            "isrc": ["USXXX1234567"],
        }
        with patch(
            "backend.server.apple_routes.get_song_info",
            new_callable=AsyncMock,
            return_value=mock_fields,
        ):
            resp = await client.get(f"/api/meta/{rowid}/apple")

        assert resp.status_code == 200
        body = resp.json()
        assert body["track_id"] == str(rowid)
        assert body["song_id"] == "1234567890"
        assert body["storefront"] == "us"
        assert body["lang"] == "zh-Hans"
        assert body["authoritative_fields"]["title"] == ["Apple Title"]
        assert body["authoritative_fields"]["artist"] == ["Apple Artist"]

    async def test_apple_fetch_song_id_from_freeform(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """tag_map 无 cnID 但有 freeform songId → 仍能提取 song_id。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

        fake_file = tmp_path / "test.m4a"
        fake_file.write_bytes(b"\x00" * 100)

        rowid = await store.insert_track(
            title="Test",
            artist="Artist",
            path=str(fake_file).replace("\\", "/"),
            codec="alac",
            duration=200000,
            tag_map='{"----:com.apple.iTunes:songId": ["9876543210"]}',
        )

        mock_fields: dict[str, list[str]] = {"title": ["Song"]}
        with patch(
            "backend.server.apple_routes.get_song_info",
            new_callable=AsyncMock,
            return_value=mock_fields,
        ):
            resp = await client.get(f"/api/meta/{rowid}/apple")

        assert resp.status_code == 200
        body = resp.json()
        assert body["song_id"] == "9876543210"

    async def test_apple_fetch_no_song_id(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """song_id 不在标签 → 400。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

        fake_file = tmp_path / "test.m4a"
        fake_file.write_bytes(b"\x00" * 100)

        rowid = await store.insert_track(
            title="Test",
            artist="Artist",
            path=str(fake_file).replace("\\", "/"),
            codec="alac",
            duration=200000,
            tag_map='{"©nam": ["Title"]}',
        )

        resp = await client.get(f"/api/meta/{rowid}/apple")
        assert resp.status_code == 400
        detail_lower = resp.json()["detail"].lower()
        assert "song_id" in detail_lower or "songid" in detail_lower

    async def test_apple_fetch_track_not_found(
        self,
        store: IndexStore,
        client: AsyncClient,
    ) -> None:
        """track 不存在 → 404。"""
        resp = await client.get("/api/meta/999999/apple")
        assert resp.status_code == 404

    async def test_apple_fetch_db_unavailable(
        self,
        app: FastAPI,
    ) -> None:
        """store 未初始化 → 503。"""
        set_store(None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/meta/1/apple")
            assert resp.status_code == 503
            assert "Database not initialized" in resp.text

    async def test_apple_fetch_invalid_track_id(
        self,
        client: AsyncClient,
    ) -> None:
        """非数字 track_id → 422。"""
        resp = await client.get("/api/meta/abc/apple")
        assert resp.status_code == 422

    async def test_apple_fetch_apple_404(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Apple API 404（歌曲不存在）→ 404。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

        fake_file = tmp_path / "test.m4a"
        fake_file.write_bytes(b"\x00" * 100)

        rowid = await store.insert_track(
            title="Test",
            artist="Artist",
            path=str(fake_file).replace("\\", "/"),
            codec="alac",
            duration=200000,
            tag_map='{"cnID": ["1234567890"]}',
        )

        with patch(
            "backend.server.apple_routes.get_song_info",
            new_callable=AsyncMock,
            side_effect=AppleAPIError("Song not found (404)", status_code=404),
        ):
            resp = await client.get(f"/api/meta/{rowid}/apple")

        assert resp.status_code == 404

    async def test_apple_fetch_apple_token_failure(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """token 抓取失败 → 503。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

        fake_file = tmp_path / "test.m4a"
        fake_file.write_bytes(b"\x00" * 100)

        rowid = await store.insert_track(
            title="Test",
            artist="Artist",
            path=str(fake_file).replace("\\", "/"),
            codec="alac",
            duration=200000,
            tag_map='{"cnID": ["1234567890"]}',
        )

        with patch(
            "backend.server.apple_routes.get_song_info",
            new_callable=AsyncMock,
            side_effect=AppleAPIError("Token fetch failed"),
        ):
            resp = await client.get(f"/api/meta/{rowid}/apple")

        assert resp.status_code == 503

    async def test_apple_fetch_path_traversal(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """path 不在 library_root 下 → 404。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

        rowid = await store.insert_track(
            title="Outside",
            artist="A",
            path="/some/other/path/file.m4a",
            codec="alac",
            duration=200000,
        )

        resp = await client.get(f"/api/meta/{rowid}/apple")
        assert resp.status_code == 404

    async def test_apple_fetch_file_not_exists(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """DB 有记录但文件不存在 → 404。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

        rowid = await store.insert_track(
            title="Ghost",
            artist="A",
            path=str(tmp_path / "nonexistent.m4a").replace("\\", "/"),
            codec="alac",
            duration=200000,
            tag_map='{"cnID": ["1234567890"]}',
        )

        resp = await client.get(f"/api/meta/{rowid}/apple")
        assert resp.status_code == 404

    async def test_apple_fetch_custom_storefront_lang(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """自定义 storefront 和 lang 参数传递正确。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

        fake_file = tmp_path / "test.m4a"
        fake_file.write_bytes(b"\x00" * 100)

        rowid = await store.insert_track(
            title="Test",
            artist="Artist",
            path=str(fake_file).replace("\\", "/"),
            codec="alac",
            duration=200000,
            tag_map='{"cnID": ["1234567890"]}',
        )

        mock_fields: dict[str, list[str]] = {"title": ["JP Title"]}
        with patch(
            "backend.server.apple_routes.get_song_info",
            new_callable=AsyncMock,
            return_value=mock_fields,
        ) as mock_fn:
            resp = await client.get(
                f"/api/meta/{rowid}/apple?storefront=jp&lang=ja",
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["storefront"] == "jp"
        assert body["lang"] == "ja"
        # 验证 get_song_info 被正确调用
        mock_fn.assert_called_once_with("1234567890", "jp", "ja")


# ---------------------------------------------------------------------------
# get_album_info 测试
# ---------------------------------------------------------------------------


def _make_album_response(
    album_id: str = "100",
    *,
    tracks: list[dict[str, object]] | None = None,
    next_url: str | None = None,
    artist_name: str = "Album Artist",
    album_name: str = "Test Album",
    copyright_val: str = "© 2024 Test Label",
    record_label: str = "Test Records",
    upc: str = "1234567890123",
) -> dict[str, object]:
    """构造 Apple amp-api albums 响应 dict。

    Args:
        album_id: 专辑 ID
        tracks: relationships.tracks.data 列表（可含 songs / 非 songs 类型）
        next_url: tracks.next（分页触发器）
    """
    if tracks is None:
        tracks = [
            {"id": "1", "type": "songs", "attributes": {"name": "Track 1"}},
            {"id": "2", "type": "songs", "attributes": {"name": "Track 2"}},
            # 非 songs 类型（music-videos 等），应被过滤
            {"id": "v1", "type": "music-videos", "attributes": {"name": "Video 1"}},
        ]

    tracks_rel: dict[str, object] = {"data": tracks, "href": "..."}
    if next_url is not None:
        tracks_rel["next"] = next_url

    return {
        "data": [
            {
                "id": album_id,
                "type": "albums",
                "attributes": {
                    "artistName": artist_name,
                    "name": album_name,
                    "artwork": {"url": "..."},
                    "releaseDate": "2024-01-15",
                    "url": "...",
                },
                "relationships": {
                    "tracks": tracks_rel,
                    "artists": {
                        "href": "...",
                        "data": [{"id": "456", "type": "artists"}],
                    },
                },
            },
        ],
    }


def _make_album_tracks_page(
    tracks: list[dict[str, object]] | None = None,
    *,
    next_url: str | None = None,
) -> dict[str, object]:
    """构造专辑 tracks 分页响应（/albums/{id}/tracks）。"""
    if tracks is None:
        tracks = [
            {"id": "3", "type": "songs", "attributes": {"name": "Track 3"}},
        ]

    page: dict[str, object] = {"data": tracks, "href": "..."}
    if next_url is not None:
        page["next"] = next_url
    return page


class TestGetAlbumInfo:
    """get_album_info mock httpx 测试。

    P2-1 覆盖：get_album_info + _fetch_album_tracks 已实现但无测试，
    补齐正常返回（含非 songs 类型过滤）+ 分页 next + 401 被动刷新 + 404。
    """

    def setup_method(self) -> None:
        TokenManager.reset_instance()

    def teardown_method(self) -> None:
        TokenManager.reset_instance()

    async def test_get_album_info_success_filters_non_songs(self) -> None:
        """mock 200 响应 → 过滤非 songs 类型 tracks，只保留 songs。"""
        tm = TokenManager.get_instance()
        exp = int(time.time()) + 3600
        tm._token = _make_jwt(exp)
        tm._token_exp = exp

        api_response = _make_album_response(
            album_id="100",
            tracks=[
                {"id": "1", "type": "songs", "attributes": {"name": "T1"}},
                {"id": "2", "type": "songs", "attributes": {"name": "T2"}},
                {"id": "v1", "type": "music-videos", "attributes": {"name": "V1"}},
            ],
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = api_response
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.meta.apple.httpx.AsyncClient", return_value=mock_client):
            result = await get_album_info("100", "us", "zh-Hans")

        # 验证返回结构
        assert "data" in result
        album_data = result["data"][0]
        assert album_data["type"] == "albums"

        # 验证非 songs 类型被过滤
        tracks_data = album_data["relationships"]["tracks"]["data"]
        track_types = [t["type"] for t in tracks_data]
        assert track_types == ["songs", "songs"]
        track_ids = [t["id"] for t in tracks_data]
        assert "v1" not in track_ids
        assert "1" in track_ids and "2" in track_ids

        # 单次请求（无分页）
        assert mock_client.get.call_count == 1

    async def test_get_album_info_pagination_next(self) -> None:
        """tracks 有 next → 递归拉取分页 + 合并 tracks。"""
        tm = TokenManager.get_instance()
        exp = int(time.time()) + 3600
        tm._token = _make_jwt(exp)
        tm._token_exp = exp

        # 首页：2 songs + next（非 songs 已被过滤前的原始数据）
        first_page = _make_album_response(
            album_id="100",
            tracks=[
                {"id": "1", "type": "songs", "attributes": {"name": "T1"}},
                {"id": "2", "type": "songs", "attributes": {"name": "T2"}},
            ],
            next_url="/v1/catalog/us/albums/100/tracks?offset=2",
        )

        # 第二页：1 song + 无 next（终止递归）
        second_page = _make_album_tracks_page(
            tracks=[
                {"id": "3", "type": "songs", "attributes": {"name": "T3"}},
                {"id": "v2", "type": "music-videos", "attributes": {"name": "V2"}},
            ],
        )

        resp_1 = MagicMock()
        resp_1.status_code = 200
        resp_1.json.return_value = first_page
        resp_1.raise_for_status = MagicMock()

        resp_2 = MagicMock()
        resp_2.status_code = 200
        resp_2.json.return_value = second_page
        resp_2.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[resp_1, resp_2])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.meta.apple.httpx.AsyncClient", return_value=mock_client):
            result = await get_album_info("100", "us", "zh-Hans")

        # 2 次请求（首页 + 分页）
        assert mock_client.get.call_count == 2

        # 合并后 tracks = 首页 2 + 第二页 1（第二页非 songs 被过滤）
        tracks_data = result["data"][0]["relationships"]["tracks"]["data"]
        track_ids = [t["id"] for t in tracks_data]
        assert track_ids == ["1", "2", "3"]
        # 非 songs 不在结果中
        assert "v2" not in track_ids

    async def test_get_album_info_401_then_200(self) -> None:
        """401 被动刷新：第一次 401 → 刷新 token → 第二次 200。"""
        tm = TokenManager.get_instance()
        exp = int(time.time()) + 3600
        old_token = _make_jwt(exp)
        new_exp = int(time.time()) + 7200
        new_token = _make_jwt(new_exp)
        tm._token = old_token
        tm._token_exp = exp

        api_response = _make_album_response(album_id="100")

        resp_401 = MagicMock()
        resp_401.status_code = 401

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = api_response
        resp_200.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[resp_401, resp_200])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("backend.meta.apple.httpx.AsyncClient", return_value=mock_client),
            patch.object(
                tm, "invalidate_and_refresh",
                new_callable=AsyncMock,
                return_value=new_token,
            ),
        ):
            result = await get_album_info("100", "us", "zh-Hans")

        # 验证返回有效
        assert result["data"][0]["id"] == "100"
        # 2 次请求（401 + 200）
        assert mock_client.get.call_count == 2

    async def test_get_album_info_404(self) -> None:
        """Apple API 404 → AppleAPIError。"""
        tm = TokenManager.get_instance()
        exp = int(time.time()) + 3600
        tm._token = _make_jwt(exp)
        tm._token_exp = exp

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.meta.apple.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(AppleAPIError, match="Album.*not found"):
                await get_album_info("999", "us", "zh-Hans")

    async def test_get_album_info_invalid_response_empty_data(self) -> None:
        """API 返回空 data → AppleAPIError。"""
        tm = TokenManager.get_instance()
        exp = int(time.time()) + 3600
        tm._token = _make_jwt(exp)
        tm._token_exp = exp

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.meta.apple.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(AppleAPIError, match="Invalid response"):
                await get_album_info("100", "us", "zh-Hans")
