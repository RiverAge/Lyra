"""Lyra Apple WebAPI 客户端。

改壳参考源 src/api.py，提供：
- 匿名 Bearer token 获取/刷新（O4 全套策略）
- get_song_info 拉取权威元数据
- get_album_info 拉取专辑元数据（含分页）

输出对齐 M4-A 已落地的 authoritative_fields 契约：
dict[str, list[str]]，key 用 writer.py:FIELD_MAP 语义字段名。

与参考源的差异：
- httpx.AsyncClient 替 hishel.AsyncCacheClient
- 去掉 creart/GlobalLogger/Measurer 耦合，换普通参数 + 标准 logging
- O4 改进：JWT exp 过期判定 + 60s 提前刷新 + asyncio.Lock 并发去重
  + 401 被动刷新（raise_for_status + 捕 401 → 刷新 → 重放 1 次）
  + IndexError 异常白名单（正则未匹配）
- 内存存储，单 worker 无需落盘
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class AppleAPIError(Exception):
    """Apple WebAPI 请求失败。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# TokenManager — 模块级单例
# ---------------------------------------------------------------------------


class TokenManager:
    """Apple 匿名 Bearer token 管理器。

    O4 全套策略：
    ① 解码 JWT exp，提前 60s 主动刷新
    ② 401 被动刷新：raise_for_status + 捕 401 → 刷新 → 重放 1 次
    ③ asyncio.Lock 并发去重：首个触发刷新，其余等锁后跳过
    ④ 启动预热（main.py on_startup 调 ensure_token）
    ⑤ 异常白名单加 IndexError（正则未匹配）
    ⑥ 内存存储，单 worker 无需落盘
    """

    _instance: TokenManager | None = None

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_exp: int | None = None  # JWT exp (epoch seconds)
        self._lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def get_instance(cls) -> TokenManager:
        """获取模块级单例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（仅测试用）。"""
        if cls._instance is not None:
            cls._instance = None

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def ensure_token(self) -> str:
        """确保有有效 token，过期/无 token 时刷新。

        Lock 并发去重：首个协程触发 _fetch_token，
        其余等锁后发现 token 已更新则直接返回，不重复抓取。
        """
        async with self._lock:
            if self._is_valid():
                return self._token  # type: ignore[return-value]
            await self._fetch_token()
            return self._token  # type: ignore[return-value]

    async def invalidate_and_refresh(self) -> str:
        """强制刷新 token（401 被动刷新用）。

        清空当前 token 后走 ensure_token（Lock 保护）。
        """
        self._token = None
        self._token_exp = None
        return await self.ensure_token()

    async def close(self) -> None:
        """关闭内部 httpx client。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _is_valid(self) -> bool:
        """token 存在且 exp 提前 60s 未过期。"""
        if not self._token or self._token_exp is None:
            return False
        return time.time() < self._token_exp - 60

    async def _fetch_token(self) -> None:
        """正则抠 JWT：GET music.apple.com → 找 JS → GET JS → 抠 eyY JWT。

        异常白名单：httpx.HTTPError + IndexError（正则未匹配）+ KeyError。
        """
        try:
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=30.0)

            # Step 1: GET music.apple.com 首页
            resp = await self._client.get(
                "https://music.apple.com", follow_redirects=True,
            )
            resp.raise_for_status()

            # Step 2: 正则找 JS bundle 路径
            js_match = re.search(r"/assets/index~[^/]+\.js", resp.text)
            if not js_match:
                raise IndexError(
                    "JS bundle path not found in Apple Music homepage"
                )
            js_uri = js_match.group(0)

            # Step 3: GET JS bundle
            js_resp = await self._client.get(
                f"https://music.apple.com{js_uri}",
            )
            js_resp.raise_for_status()

            # Step 4: 正则抠 JWT
            jwt_match = re.search(
                r"(eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+)",
                js_resp.text,
            )
            if not jwt_match:
                raise IndexError("JWT not found in JS bundle")
            self._token = jwt_match.group(1)

            # Step 5: 解码 JWT payload 取 exp
            self._token_exp = _decode_jwt_exp(self._token)
            logger.info(
                "Apple token fetched, expires at %d (in %.0f seconds)",
                self._token_exp,
                self._token_exp - time.time(),
            )
        except (httpx.HTTPError, IndexError, KeyError) as e:
            logger.warning(
                "Failed to fetch Apple token: %s: %s",
                type(e).__name__,
                e,
            )
            raise

    # 便于测试：子类可覆盖 _fetch_token
    # （不使用，测试通过直接设置 _token/_token_exp 绕过网络）


# ---------------------------------------------------------------------------
# JWT 解码辅助
# ---------------------------------------------------------------------------


def _decode_jwt_exp(token: str) -> int:
    """base64url 解码 JWT payload 第二段，取 exp 字段。

    Returns:
        exp 值（epoch seconds, int）
    """
    parts = token.split(".")
    if len(parts) < 2:
        raise KeyError("Invalid JWT format: expected 3 parts")
    payload_b64 = parts[1]
    # 补齐 base64url padding
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    return int(payload["exp"])


# ---------------------------------------------------------------------------
# 请求头常量
# ---------------------------------------------------------------------------

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/91.0.4472.124 Safari/537.36"
)

_AMP_HEADERS_TEMPLATE: dict[str, str] = {
    "User-Agent": _USER_AGENT,
    "Origin": "https://music.apple.com",
}


# ---------------------------------------------------------------------------
# get_song_info
# ---------------------------------------------------------------------------


async def get_song_info(
    song_id: str,
    storefront: str = "us",
    lang: str = "zh-Hans",
) -> dict[str, list[str]]:
    """拉取 Apple amp-api song 元数据，返回 authoritative_fields。

    输出格式：dict[str, list[str]]，key 为 writer.py:FIELD_MAP 语义字段名。
    不在 FIELD_MAP 中的字段放入 "raw" 子字典（前端可展示但不进 diff/write）。

    Args:
        song_id: Apple Music song ID（如 "1234567890"）
        storefront: 区域代码（如 "us", "cn", "jp"）
        lang: 语言代码（如 "zh-Hans", "en-US"）

    Returns:
        authoritative_fields dict，含 FIELD_MAP 语义字段 + raw 子字典。

    Raises:
        AppleAPIError: 404（歌曲不存在）/ 网络错误 / token 失败
    """
    tm = TokenManager.get_instance()
    token = await tm.ensure_token()

    headers = {**_AMP_HEADERS_TEMPLATE, "Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        url = (
            f"https://amp-api.music.apple.com/v1/catalog/{storefront}"
            f"/songs/{song_id}"
        )
        params = {
            "extend": "extendedAssetUrls",
            "include": "albums,explicit",
            "l": lang,
        }

        resp = await client.get(url, params=params, headers=headers)

        # 401 被动刷新：刷新 token → 重放 1 次
        if resp.status_code == 401:
            logger.info("Apple API 401, refreshing token and retrying...")
            token = await tm.invalidate_and_refresh()
            headers["Authorization"] = f"Bearer {token}"
            resp = await client.get(url, params=params, headers=headers)

        if resp.status_code == 404:
            raise AppleAPIError(
                f"Song {song_id} not found (404)", status_code=404,
            )
        resp.raise_for_status()

        data = resp.json()
        if "errors" in data or "data" not in data:
            raise AppleAPIError(
                f"Invalid response for song {song_id}: "
                f"{data.get('errors', 'no data field')}",
            )

    return _map_song_attributes(data, song_id)


# ---------------------------------------------------------------------------
# get_album_info
# ---------------------------------------------------------------------------


async def get_album_info(
    album_id: str,
    storefront: str = "us",
    lang: str = "zh-Hans",
) -> dict[str, object]:
    """拉取 Apple amp-api 专辑元数据（含 tracks 分页，每页 300）。

    Args:
        album_id: Apple Music album ID
        storefront: 区域代码
        lang: 语言代码

    Returns:
        专辑原始数据 dict（含 data[0].attributes + relationships.tracks）。

    Raises:
        AppleAPIError: 404 / 网络错误 / token 失败
    """
    tm = TokenManager.get_instance()
    token = await tm.ensure_token()

    headers = {**_AMP_HEADERS_TEMPLATE, "Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        url = (
            f"https://amp-api.music.apple.com/v1/catalog/{storefront}"
            f"/albums/{album_id}"
        )
        params = {
            "omit[resource]": "autos",
            "include": "tracks,artists,record-labels",
            "include[songs]": "artists",
            "fields[artists]": "name",
            "fields[albums:albums]": "artistName,artwork,name,releaseDate,url",
            "fields[record-labels]": "name",
            "l": lang,
        }

        resp = await client.get(url, params=params, headers=headers)

        # 401 被动刷新
        if resp.status_code == 401:
            logger.info("Apple API 401, refreshing token and retrying...")
            token = await tm.invalidate_and_refresh()
            headers["Authorization"] = f"Bearer {token}"
            resp = await client.get(url, params=params, headers=headers)

        if resp.status_code == 404:
            raise AppleAPIError(
                f"Album {album_id} not found (404)", status_code=404,
            )
        resp.raise_for_status()

        data = resp.json()
        if "data" not in data or not data["data"]:
            raise AppleAPIError(f"Invalid response for album {album_id}")

        # 过滤非 songs 类型的 tracks
        album_data = data["data"][0]
        tracks_rel = album_data.get("relationships", {}).get("tracks", {})
        track_list = tracks_rel.get("data", [])
        filtered = [t for t in track_list if t.get("type") == "songs"]
        album_data["relationships"]["tracks"]["data"] = filtered

        # 分页：tracks 有 next → 递归拉取
        next_url = tracks_rel.get("next")
        if next_url:
            all_tracks = await _fetch_album_tracks(
                client, album_id, storefront, lang, headers, next_url,
            )
            album_data["relationships"]["tracks"]["data"] = (
                filtered + all_tracks
            )

    return data


async def _fetch_album_tracks(
    client: httpx.AsyncClient,
    album_id: str,
    storefront: str,
    lang: str,
    headers: dict[str, str],
    next_url: str | None,
    offset: int = 0,
) -> list[dict[str, object]]:
    """递归拉取专辑 tracks 分页（每页 300）。"""
    if next_url is None:
        return []

    url = (
        f"https://amp-api.music.apple.com/v1/catalog/{storefront}"
        f"/albums/{album_id}/tracks?offset={offset}"
    )
    params: dict[str, str] = {"l": lang}

    resp = await client.get(url, params=params, headers=headers)

    if resp.status_code == 401:
        tm = TokenManager.get_instance()
        token = await tm.invalidate_and_refresh()
        headers["Authorization"] = f"Bearer {token}"
        resp = await client.get(url, params=params, headers=headers)

    resp.raise_for_status()
    data = resp.json()

    tracks = data.get("data", [])
    filtered = [t for t in tracks if t.get("type") == "songs"]

    if data.get("next"):
        more = await _fetch_album_tracks(
            client, album_id, storefront, lang, headers,
            data["next"], offset + 300,
        )
        return filtered + more

    return filtered


# ---------------------------------------------------------------------------
# 属性映射：SongData.Attributes → FIELD_MAP 语义字段名
# ---------------------------------------------------------------------------


def _map_song_attributes(
    api_data: dict[str, object],
    song_id: str,
) -> dict[str, list[str]]:
    """将 Apple API song 响应映射为 authoritative_fields。

    输出格式：dict[str, list[str]]
    - key 在 FIELD_MAP 中的 → 直接映射（进 diff/write 流水线）
    - key 不在 FIELD_MAP 中的 → 放入 "raw" 子字典（前端可展示，不进 diff/write）

    映射对照表（SongData.Attributes → FIELD_MAP 语义名）：
        name           → title
        artistName     → artist
        albumName      → album
        composerName   → composer
        genreNames     → genre
        isrc           → isrc
    从 album relationship 提取：
        artistName     → album_artist
        copyright      → copyright
        recordLabel    → record_company
        upc            → barcode
    不在 FIELD_MAP → raw：
        releaseDate, trackNumber, discNumber, durationInMillis,
        contentRating, hasLyrics, hasTimeSyncedLyrics, hasCredits,
        isAppleDigitalMaster, isMasteredForItunes, audioTraits,
        artwork, playParams, url, previews, extendedAssetUrls

    Args:
        api_data: Apple API 响应 JSON dict
        song_id: 用于定位正确的 datum

    Returns:
        authoritative_fields dict
    """
    # 找到匹配 song_id 的 datum
    raw_data = api_data.get("data", [])
    data_list: list[object] = raw_data if isinstance(raw_data, list) else []
    datum: dict[str, object] | None = None
    for d in data_list:
        if isinstance(d, dict) and d.get("id") == song_id:
            datum = d
            break
    if datum is None:
        raise AppleAPIError(f"Song {song_id} not found in API response")

    attrs = datum.get("attributes", {})
    if not isinstance(attrs, dict):
        attrs = {}

    result: dict[str, list[str]] = {}
    raw: dict[str, object] = {}

    # -- 直接映射（song attributes → FIELD_MAP 语义名） --
    _str_field(attrs, "name", result, "title")
    _str_field(attrs, "artistName", result, "artist")
    _str_field(attrs, "albumName", result, "album")
    _str_field(attrs, "composerName", result, "composer")
    _list_field(attrs, "genreNames", result, "genre")
    _str_field(attrs, "isrc", result, "isrc")

    # -- 从 album relationship 提取 --
    relationships = datum.get("relationships", {})
    if isinstance(relationships, dict):
        albums_rel = relationships.get("albums", {})
        if isinstance(albums_rel, dict):
            album_data_list = albums_rel.get("data", [])
            if isinstance(album_data_list, list) and album_data_list:
                album_attrs = album_data_list[0].get("attributes", {})
                if isinstance(album_attrs, dict):
                    _str_field(album_attrs, "artistName", result, "album_artist")
                    _str_field(album_attrs, "copyright", result, "copyright")
                    _str_field(album_attrs, "recordLabel", result, "record_company")
                    _str_field(album_attrs, "upc", result, "barcode")

    # -- 不在 FIELD_MAP 的字段 → raw --
    _raw_str(attrs, "releaseDate", raw)
    _raw_int(attrs, "trackNumber", raw)
    _raw_int(attrs, "discNumber", raw)
    _raw_int(attrs, "durationInMillis", raw)
    _raw_str(attrs, "contentRating", raw)
    _raw_bool(attrs, "hasLyrics", raw)
    _raw_bool(attrs, "hasTimeSyncedLyrics", raw)
    _raw_bool(attrs, "hasCredits", raw)
    _raw_bool(attrs, "isAppleDigitalMaster", raw)
    _raw_bool(attrs, "isMasteredForItunes", raw)
    _raw_list(attrs, "audioTraits", raw)

    if raw:
        # raw 的 value 统一为 list[str] 以保持接口一致
        raw_fields: dict[str, list[str]] = {}
        for k, v in raw.items():
            if isinstance(v, list):
                raw_fields[k] = [str(item) for item in v]
            else:
                raw_fields[k] = [str(v)]
        result["raw"] = [json.dumps(raw_fields, ensure_ascii=False)]

    return result


# ---------------------------------------------------------------------------
# 映射辅助函数
# ---------------------------------------------------------------------------


def _str_field(
    attrs: dict[str, object],
    api_key: str,
    result: dict[str, list[str]],
    semantic: str,
) -> None:
    """从 attrs 取字符串字段，放入 result[semantic] = [value]。"""
    val = attrs.get(api_key)
    if val is not None and val != "":
        result[semantic] = [str(val)]


def _list_field(
    attrs: dict[str, object],
    api_key: str,
    result: dict[str, list[str]],
    semantic: str,
) -> None:
    """从 attrs 取列表字段，放入 result[semantic] = list[str]。"""
    val = attrs.get(api_key)
    if val is not None:
        if isinstance(val, list):
            result[semantic] = [str(v) for v in val if v is not None]
        else:
            result[semantic] = [str(val)]


def _raw_str(
    attrs: dict[str, object],
    api_key: str,
    raw: dict[str, object],
) -> None:
    """从 attrs 取字符串字段放入 raw dict。"""
    val = attrs.get(api_key)
    if val is not None and val != "":
        raw[api_key] = str(val)


def _raw_int(
    attrs: dict[str, object],
    api_key: str,
    raw: dict[str, object],
) -> None:
    """从 attrs 取整数字段放入 raw dict。"""
    val = attrs.get(api_key)
    if val is not None:
        try:
            raw[api_key] = int(str(val))
        except (ValueError, TypeError):
            raw[api_key] = str(val)


def _raw_bool(
    attrs: dict[str, object],
    api_key: str,
    raw: dict[str, object],
) -> None:
    """从 attrs 取布尔字段放入 raw dict。"""
    val = attrs.get(api_key)
    if val is not None:
        raw[api_key] = bool(val)


def _raw_list(
    attrs: dict[str, object],
    api_key: str,
    raw: dict[str, object],
) -> None:
    """从 attrs 取列表字段放入 raw dict。"""
    val = attrs.get(api_key)
    if val is not None and isinstance(val, list) and len(val) > 0:
        raw[api_key] = val
