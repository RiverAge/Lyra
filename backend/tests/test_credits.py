"""测试——Credits 爬取模块 + credits_routes。

覆盖：
- role_map 加载 + mtime 热重载
- 落地页守卫（song_id not in body → None）
- _NO_CREDITS_SENTINEL（有效真实页无 roleNames → 哨兵）
- process_credits_data（映射 + performer 聚合）
- 串行 region fallback
- credits_routes 端点（200/400/404/503）
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.index.store import IndexStore, set_store
from backend.meta.credits import (
    _NO_CREDITS_SENTINEL,
    _fetch_single_region,
    _is_sentinel_check,
    fetch_credits,
    get_credits,
    get_role_map,
    process_credits_data,
)
from backend.server.credits_routes import credits_router

# asyncio_mode = "auto" 由 pyproject.toml 设定

# ---------------------------------------------------------------------------
# 共享常量
# ---------------------------------------------------------------------------

_ROLE_MAP_SRC = Path(
    "C:/Users/Mercury/Downloads/AppleMusicDecrypt-Windows/data/role_map.toml",
)
_FIXTURE_DIR = Path(
    "C:/Users/Mercury/Desktop/src/media/navidrome/tests/fixtures",
)


# ---------------------------------------------------------------------------
# 辅助：构建 mock 网页响应
# ---------------------------------------------------------------------------


def _make_credits_html(
    song_id: str = "123456",
    *,
    has_song_id: bool = True,
    has_script: bool = True,
    has_song_detail: bool = True,
    sections: list[dict] | None = None,
) -> str:
    """构建模拟 Apple Music 网页 HTML。

    Args:
        song_id: 歌曲ID，用于落地页守卫检测。
        has_song_id: body 中是否包含 song_id（False 触发落地页守卫）。
        has_script: 是否包含 serialized-server-data script。
        has_song_detail: sections 中是否包含 songDetail。
        sections: 自定义 sections 数据（覆盖默认）。
    """
    song_id_text = song_id if has_song_id else "OTHER_ID"

    if sections is None:
        sections = []

    script_content = json.dumps({
        "data": [{
            "data": {
                "sections": sections,
            },
        }],
    })

    html = "<html><body>"
    html += f"<div>Song {song_id_text}</div>"
    if has_script:
        html += (
            f'<script id="serialized-server-data">'
            f"{script_content}</script>"
        )
    html += "</body></html>"
    return html


def _make_sections_with_roles(
    *,
    include_song_detail: bool = True,
) -> list[dict]:
    """构建含 roleNames 的 sections 数据。"""
    sections: list[dict] = []

    if include_song_detail:
        sections.append({
            "id": "songDetail",
            "itemKind": "songDetailHeader",
            "items": [],
        })

    sections.append({
        "id": "credits-section",
        "title": "制作人员",
        "items": [
            {
                "name": "张三",
                "roleNames": ["作曲", "制作人"],
            },
            {
                "name": "李四",
                "roleNames": ["作词"],
            },
            {
                "name": "王五",
                "roleNames": ["混音工程师", "吉他"],
            },
        ],
    })

    return sections


def _make_sections_no_roles(
    *,
    include_song_detail: bool = True,
) -> list[dict]:
    """构建不含 roleNames 的 sections（触发哨兵或 None）。"""
    if include_song_detail:
        return [{
            "id": "songDetail",
            "itemKind": "songDetailHeader",
            "items": [{"name": "Some Song"}],
        }]
    return [{
        "id": "otherSection",
        "items": [{"name": "Some Item"}],
    }]


# ---------------------------------------------------------------------------
# TestRoleMap
# ---------------------------------------------------------------------------


class TestRoleMap:
    """role_map.toml 加载 + mtime 热重载测试。"""

    async def test_load_role_map(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """加载 role_map.toml → 返回非空 dict，含已知 key。"""
        dst = tmp_path / "role_map.toml"
        shutil.copy2(_ROLE_MAP_SRC, dst)

        import backend.meta.credits as _mod
        monkeypatch.setattr(_mod, "_mtime_cache", None)
        monkeypatch.setattr(_mod, "_map_cache", None)
        monkeypatch.setattr(_mod, "_ROLE_MAP_FILE", dst)

        result = get_role_map()
        assert isinstance(result, dict)
        assert len(result) > 0
        # 验证中文 key 存在
        assert "作曲" in result
        # 验证结构：(target_tag_or_None, display)
        composer_entry = result["作曲"]
        assert composer_entry[0] == "composer"  # target_tag
        assert isinstance(composer_entry[1], str)  # display

    async def test_mtime_hot_reload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """mtime 变化后重读 toml。"""
        dst = tmp_path / "role_map.toml"
        shutil.copy2(_ROLE_MAP_SRC, dst)

        import backend.meta.credits as _mod
        monkeypatch.setattr(_mod, "_mtime_cache", None)
        monkeypatch.setattr(_mod, "_map_cache", None)
        monkeypatch.setattr(_mod, "_ROLE_MAP_FILE", dst)

        # 首次加载
        result1 = get_role_map()
        assert "作曲" in result1

        # 修改 toml mtime（触摸文件）
        new_mtime = dst.stat().st_mtime + 100
        os.utime(dst, (new_mtime, new_mtime))

        # 再次加载应触发重读
        result2 = get_role_map()
        assert "作曲" in result2

    async def test_missing_role_map_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """role_map.toml 不存在时返回空 dict。"""
        import backend.meta.credits as _mod
        monkeypatch.setattr(_mod, "_mtime_cache", None)
        monkeypatch.setattr(_mod, "_map_cache", None)
        monkeypatch.setattr(
            _mod, "_ROLE_MAP_FILE", tmp_path / "nonexistent.toml",
        )

        result = get_role_map()
        assert result == {}


# ---------------------------------------------------------------------------
# TestLandingPageGuard
# ---------------------------------------------------------------------------


class TestLandingPageGuard:
    """落地页守卫：body 不含 song_id → None。"""

    async def test_landing_page_guard_returns_none(self) -> None:
        """200 但 song_id 不在 body → 返回 None。"""
        import httpx

        html = _make_credits_html(
            song_id="123456", has_song_id=False,
        )
        mock_response = httpx.Response(
            status_code=200,
            text=html,
            request=httpx.Request("GET", "https://example.com"),
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await _fetch_single_region(
            song_id="123456",
            region="cn",
            client=mock_client,
            base_url="https://music.587626.xyz",
        )
        assert result is None


# ---------------------------------------------------------------------------
# TestSentinel
# ---------------------------------------------------------------------------


class TestSentinel:
    """有效真实页无 roleNames → _NO_CREDITS_SENTINEL。"""

    async def test_valid_page_no_roles_returns_sentinel(self) -> None:
        """有效页（有 songDetail）但无 roleNames → 返回哨兵。"""
        import httpx

        sections = _make_sections_no_roles(include_song_detail=True)
        html = _make_credits_html(song_id="123456", sections=sections)
        mock_response = httpx.Response(
            status_code=200,
            text=html,
            request=httpx.Request("GET", "https://example.com"),
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await _fetch_single_region(
            song_id="123456",
            region="cn",
            client=mock_client,
            base_url="https://music.587626.xyz",
        )
        assert result is _NO_CREDITS_SENTINEL

    async def test_invalid_page_no_roles_returns_none(self) -> None:
        """无效页（无 songDetail）且无 roleNames → 返回 None。"""
        import httpx

        sections = _make_sections_no_roles(include_song_detail=False)
        html = _make_credits_html(song_id="123456", sections=sections)
        mock_response = httpx.Response(
            status_code=200,
            text=html,
            request=httpx.Request("GET", "https://example.com"),
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await _fetch_single_region(
            song_id="123456",
            region="cn",
            client=mock_client,
            base_url="https://music.587626.xyz",
        )
        assert result is None

    async def test_is_sentinel_check(self) -> None:
        """_is_sentinel_check 正确识别哨兵。"""
        assert _is_sentinel_check(_NO_CREDITS_SENTINEL) is True
        assert _is_sentinel_check({"data": []}) is False
        assert _is_sentinel_check(None) is False


# ---------------------------------------------------------------------------
# TestProcessCreditsData
# ---------------------------------------------------------------------------


class TestProcessCreditsData:
    """process_credits_data 映射 + performer 聚合测试。"""

    async def test_process_credits_basic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """mock 含 roleNames 的 JSON → authoritative_fields 对齐 FIELD_MAP。"""
        dst = tmp_path / "role_map.toml"
        shutil.copy2(_ROLE_MAP_SRC, dst)

        import backend.meta.credits as _mod
        monkeypatch.setattr(_mod, "_mtime_cache", None)
        monkeypatch.setattr(_mod, "_map_cache", None)
        monkeypatch.setattr(_mod, "_ROLE_MAP_FILE", dst)

        # 构造 API 兼容格式数据
        json_data = {
            "data": [{
                "attributes": {
                    "title": "制作人员", "kind": "credits-section",
                },
                "relationships": {
                    "credit-artists": {
                        "data": [
                            {
                                "id": "web_张三",
                                "attributes": {
                                    "name": "张三",
                                    "roleNames": ["作曲", "制作人"],
                                },
                            },
                            {
                                "id": "web_李四",
                                "attributes": {
                                    "name": "李四",
                                    "roleNames": ["作词"],
                                },
                            },
                            {
                                "id": "web_王五",
                                "attributes": {
                                    "name": "王五",
                                    "roleNames": ["混音工程师", "吉他"],
                                },
                            },
                        ],
                    },
                },
            }],
        }

        auth_fields, missing_roles = process_credits_data(json_data)

        assert auth_fields is not None
        # 验证标准字段
        assert "composer" in auth_fields
        assert "张三" in auth_fields["composer"]

        assert "lyricist" in auth_fields
        assert "李四" in auth_fields["lyricist"]

        assert "producer" in auth_fields
        assert "张三" in auth_fields["producer"]

        assert "mixer" in auth_fields
        assert "王五" in auth_fields["mixer"]

        # performer 聚合
        assert "performer" in auth_fields
        performers = auth_fields["performer"]
        # 张三有 Composer + Producer 角色
        zs_entry = next((p for p in performers if p.startswith("张三")), None)
        assert zs_entry is not None
        assert "Composer" in zs_entry
        assert "Producer" in zs_entry

        # 王五有吉他（target_tag=""，仅进 performer）
        ww_entry = next(
            (p for p in performers if p.startswith("王五")), None,
        )
        assert ww_entry is not None

        # 缺失角色
        assert isinstance(missing_roles, set)

    async def test_process_sentinel_returns_none(self) -> None:
        """哨兵输入 → 返回 None。"""
        auth_fields, missing = process_credits_data(_NO_CREDITS_SENTINEL)
        assert auth_fields is None
        assert missing == set()

    async def test_process_none_returns_none(self) -> None:
        """None 输入 → 返回 None。"""
        auth_fields, missing = process_credits_data(None)
        assert auth_fields is None
        assert missing == set()

    async def test_process_empty_data_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """空数据 → 返回 None。"""
        dst = tmp_path / "role_map.toml"
        shutil.copy2(_ROLE_MAP_SRC, dst)

        import backend.meta.credits as _mod
        monkeypatch.setattr(_mod, "_mtime_cache", None)
        monkeypatch.setattr(_mod, "_map_cache", None)
        monkeypatch.setattr(_mod, "_ROLE_MAP_FILE", dst)

        auth_fields, missing = process_credits_data({"data": []})
        assert auth_fields is None

    async def test_performer_aggregation_dedup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """同一人在多个 section 出现 → performer 去重。"""
        dst = tmp_path / "role_map.toml"
        shutil.copy2(_ROLE_MAP_SRC, dst)

        import backend.meta.credits as _mod
        monkeypatch.setattr(_mod, "_mtime_cache", None)
        monkeypatch.setattr(_mod, "_map_cache", None)
        monkeypatch.setattr(_mod, "_ROLE_MAP_FILE", dst)

        json_data = {
            "data": [
                {
                    "attributes": {"title": "A", "kind": "a"},
                    "relationships": {
                        "credit-artists": {
                            "data": [{
                                "id": "web_张三",
                                "attributes": {
                                    "name": "张三",
                                    "roleNames": ["作曲"],
                                },
                            }],
                        },
                    },
                },
                {
                    "attributes": {"title": "B", "kind": "b"},
                    "relationships": {
                        "credit-artists": {
                            "data": [{
                                "id": "web_张三",
                                "attributes": {
                                    "name": "张三",
                                    "roleNames": ["制作人"],
                                },
                            }],
                        },
                    },
                },
            ],
        }

        auth_fields, _ = process_credits_data(json_data)
        assert auth_fields is not None
        performers = auth_fields.get("performer", [])
        # 张三只出现一次，但含两个角色
        zs_entries = [p for p in performers if p.startswith("张三")]
        assert len(zs_entries) == 1
        assert "Composer" in zs_entries[0]
        assert "Producer" in zs_entries[0]


# ---------------------------------------------------------------------------
# TestSerialFallback
# ---------------------------------------------------------------------------


class TestSerialFallback:
    """串行 region fallback 测试。"""

    async def test_primary_success(self) -> None:
        """primary region 成功 → 直接返回，不 fallback。"""
        import httpx

        sections = _make_sections_with_roles()
        html = _make_credits_html(song_id="123456", sections=sections)
        mock_response = httpx.Response(
            status_code=200,
            text=html,
            request=httpx.Request("GET", "https://example.com"),
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        result = await fetch_credits(
            song_id="123456",
            primary_region="cn",
            client=mock_client,
            base_url="https://music.587626.xyz",
        )
        assert result is not None
        assert not _is_sentinel_check(result)
        # 只调用了一次（primary）
        assert mock_client.get.call_count == 1

    async def test_primary_fail_us_success(self) -> None:
        """primary 失败 → fallback us 成功。"""
        import httpx

        sections = _make_sections_with_roles()
        good_html = _make_credits_html(song_id="123456", sections=sections)
        good_response = httpx.Response(
            status_code=200,
            text=good_html,
            request=httpx.Request("GET", "https://example.com"),
        )

        fail_response = httpx.Response(
            status_code=404,
            text="Not Found",
            request=httpx.Request("GET", "https://example.com"),
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(
            side_effect=[fail_response, good_response],
        )
        mock_client.aclose = AsyncMock()

        # Patch asyncio.sleep to avoid actual delay in tests
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await fetch_credits(
                song_id="123456",
                primary_region="cn",
                client=mock_client,
                base_url="https://music.587626.xyz",
            )
        assert result is not None
        assert not _is_sentinel_check(result)

    async def test_primary_sentinel_no_fallback(self) -> None:
        """primary 返回哨兵 → 立即返回，不 fallback。"""
        import httpx

        sections = _make_sections_no_roles(include_song_detail=True)
        html = _make_credits_html(song_id="123456", sections=sections)
        sentinel_response = httpx.Response(
            status_code=200,
            text=html,
            request=httpx.Request("GET", "https://example.com"),
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=sentinel_response)
        mock_client.aclose = AsyncMock()

        result = await fetch_credits(
            song_id="123456",
            primary_region="cn",
            client=mock_client,
            base_url="https://music.587626.xyz",
        )
        assert result is _NO_CREDITS_SENTINEL
        # 只调用了一次（primary），没有 fallback
        assert mock_client.get.call_count == 1

    async def test_all_regions_fail(self) -> None:
        """全 region 失败 → 返回 None。"""
        import httpx

        fail_response = httpx.Response(
            status_code=500,
            text="Server Error",
            request=httpx.Request("GET", "https://example.com"),
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=fail_response)
        mock_client.aclose = AsyncMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await fetch_credits(
                song_id="123456",
                primary_region="cn",
                client=mock_client,
                base_url="https://music.587626.xyz",
            )
        assert result is None


# ---------------------------------------------------------------------------
# TestGetCredits — 一站式入口
# ---------------------------------------------------------------------------


class TestGetCredits:
    """get_credits 一站式入口测试。"""

    async def test_get_credits_returns_authoritative_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """一站式：爬取 + 映射 → 返回 authoritative_fields。"""
        dst = tmp_path / "role_map.toml"
        shutil.copy2(_ROLE_MAP_SRC, dst)

        import backend.meta.credits as _mod
        monkeypatch.setattr(_mod, "_mtime_cache", None)
        monkeypatch.setattr(_mod, "_map_cache", None)
        monkeypatch.setattr(_mod, "_ROLE_MAP_FILE", dst)

        mock_credits_data = {
            "data": [{
                "attributes": {
                    "title": "制作人员", "kind": "credits",
                },
                "relationships": {
                    "credit-artists": {
                        "data": [{
                            "id": "web_张三",
                            "attributes": {
                                "name": "张三",
                                "roleNames": ["作曲"],
                            },
                        }],
                    },
                },
            }],
        }

        with patch(
            "backend.meta.credits.fetch_credits",
            new_callable=AsyncMock,
            return_value=mock_credits_data,
        ):
            result = await get_credits("123456", "us")

        assert result is not None
        assert "composer" in result
        assert "张三" in result["composer"]

    async def test_get_credits_sentinel(self) -> None:
        """哨兵透传。"""
        with patch(
            "backend.meta.credits.fetch_credits",
            new_callable=AsyncMock,
            return_value=_NO_CREDITS_SENTINEL,
        ):
            result = await get_credits("123456", "us")

        assert result is _NO_CREDITS_SENTINEL

    async def test_get_credits_none(self) -> None:
        """全 region 失败 → None。"""
        with patch(
            "backend.meta.credits.fetch_credits",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await get_credits("123456", "us")

        assert result is None


# ---------------------------------------------------------------------------
# credits_routes 测试 — fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """创建含 credits_router 的测试 app。"""
    app_fast = FastAPI()
    app_fast.include_router(credits_router, prefix="/api")
    return app_fast


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """返回已绑定测试 app 的 httpx AsyncClient。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# TestCreditsRoute
# ---------------------------------------------------------------------------


class TestCreditsRoute:
    """GET /api/meta/{track_id}/credits 测试。"""

    async def _prepare_track(
        self,
        store: IndexStore,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        tag_map: str = '{"cnID": ["123456"], "©nam": ["Test Song"]}',
        title: str = "Test Song",
    ) -> int:
        """辅助：创建测试音频文件并插入 store。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))

        src = _FIXTURE_DIR / "test.m4a"
        dst = tmp_path / "test.m4a"
        if src.exists():
            shutil.copy2(src, dst)
        else:
            dst.write_bytes(b"\x00" * 100)

        return await store.insert_track(
            title=title,
            artist="Artist",
            path=str(dst).replace("\\", "/"),
            codec="alac",
            duration=200000,
            tag_map=tag_map,
        )

    async def test_credits_returns_authoritative_fields(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """正常请求 → 200 + authoritative_fields。"""
        rowid = await self._prepare_track(store, tmp_path, monkeypatch)

        mock_auth_fields = {
            "composer": ["张三"],
            "lyricist": ["李四"],
            "performer": ["张三 (Composer)", "李四 (Lyricist)"],
        }
        with patch(
            "backend.server.credits_routes.get_credits",
            new_callable=AsyncMock,
            return_value=mock_auth_fields,
        ):
            resp = await client.get(
                f"/api/meta/{rowid}/credits",
                params={"storefront": "us"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "authoritative_fields" in body
        assert body["authoritative_fields"]["composer"] == ["张三"]
        assert body["authoritative_fields"]["lyricist"] == ["李四"]

    async def test_credits_no_song_id(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """tag_map 中无 cnID → 400。"""
        rowid = await self._prepare_track(
            store, tmp_path, monkeypatch,
            tag_map='{"©nam": ["No Song ID"]}',
            title="No Song ID",
        )

        resp = await client.get(
            f"/api/meta/{rowid}/credits",
            params={"storefront": "us"},
        )
        assert resp.status_code == 400
        assert "No Apple Music Song ID" in resp.text

    async def test_credits_sentinel(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """哨兵 → 200 + no_credits。"""
        rowid = await self._prepare_track(
            store, tmp_path, monkeypatch,
            tag_map='{"cnID": ["999999"], "©nam": ["No Credits Song"]}',
            title="No Credits Song",
        )

        with patch(
            "backend.server.credits_routes.get_credits",
            new_callable=AsyncMock,
            return_value=_NO_CREDITS_SENTINEL,
        ):
            resp = await client.get(
                f"/api/meta/{rowid}/credits",
                params={"storefront": "us"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body.get("no_credits") is True

    async def test_credits_all_regions_fail(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """全 region 失败 → 503。"""
        rowid = await self._prepare_track(
            store, tmp_path, monkeypatch,
            tag_map='{"cnID": ["111111"], "©nam": ["Failed Song"]}',
            title="Failed Song",
        )

        with patch(
            "backend.server.credits_routes.get_credits",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.get(
                f"/api/meta/{rowid}/credits",
                params={"storefront": "us"},
            )

        assert resp.status_code == 503
        assert "Failed to fetch credits" in resp.text

    async def test_credits_track_not_found(
        self,
        store: IndexStore,
        client: AsyncClient,
    ) -> None:
        """不存在的 track_id → 404。"""
        resp = await client.get(
            "/api/meta/999999/credits", params={"storefront": "us"},
        )
        assert resp.status_code == 404

    async def test_credits_db_unavailable(
        self,
        app: FastAPI,
    ) -> None:
        """store 未初始化 → 503。"""
        set_store(None)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test",
        ) as c:
            resp = await c.get(
                "/api/meta/1/credits", params={"storefront": "us"},
            )
            assert resp.status_code == 503
            assert "Database not initialized" in resp.text

    async def test_credits_invalid_track_id(
        self,
        client: AsyncClient,
    ) -> None:
        """非数字 track_id → 422。"""
        resp = await client.get(
            "/api/meta/abc/credits", params={"storefront": "us"},
        )
        assert resp.status_code == 422
