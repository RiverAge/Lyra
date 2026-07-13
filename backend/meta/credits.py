"""Lyra 制作人员信息（Credits）爬取模块。

从 Apple Music 网页版爬取制作人员名单，按 role_map.toml 映射为
authoritative_fields（语义字段名 → list[str]），供 diff 对比 + 写入。

设计要点：
- 串行 region fallback（O5 简化，去掉 WrapperManager 依赖）
- _NO_CREDITS_SENTINEL 哨兵（永久无 credits 不重试/fallback）
- 落地页守卫（song_id not in body → None，防 CF 缓存错页）
- role_map.toml mtime 惰性热重载
- httpx.AsyncClient 替 requests，asyncio.sleep 替 time.sleep

改壳参考源：C:/Users/Mercury/Downloads/AppleMusicDecrypt-Windows/src/credits.py
去掉的耦合：WrapperManager（动态区退化为内置候选表）、tenacity（串行 fallback
自带重试语义）、process_state.json/credits_pending_roles.json（落库后续补）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import tomllib
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# role_map.toml 路径：Lyra/data/role_map.toml
_ROLE_MAP_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "role_map.toml"

# CF Worker 代理地址（默认），可通过 LYRA_CREDITS_BASE_URL 环境变量覆盖
_DEFAULT_CREDITS_BASE_URL = "https://music.587626.xyz"

# 串行 region fallback 候选表（O5 简化：去掉 WrapperManager 动态区）
_DEFAULT_FALLBACK_REGIONS = ["us", "jp", "gb", "kr", "tw", "de", "fr", "au", "cn"]

# 串行 fallback 每次请求后 sleep（防限流，经验值）
API_DELAY = 0.3

# 哨兵：歌曲页面是有效真实页（song_id 命中、有 songDetail 结构）但无 roleNames。
# 说明歌曲确实上架、但 Apple 未录入制作人员信息——属于「永久无 credits」，
# 重试/fallback 都拿不到。与 None（临时失败）区分开。
_NO_CREDITS_SENTINEL: dict[str, bool] = {"__no_credits__": True}

# 爬取请求头（照搬参考源）
_CREDITS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ---------------------------------------------------------------------------
# role_map.toml 读取 + mtime 惰性热重载
# ---------------------------------------------------------------------------

_mtime_cache: float | None = None
_map_cache: dict[str, tuple[str | None, str]] | None = None


def get_role_map() -> dict[str, tuple[str | None, str]]:
    """读取 data/role_map.toml，返回 {roleName: (target_tag_or_None, display)}。

    按 mtime 惰性缓存：文件没改就用上次结果；一旦 toml 被编辑（mtime 变），
    下次调用自动重读。这样改 toml 不用重启进程。

    解析失败不抛异常，返回空 dict（退化为"所有角色都 missing"）。
    """
    global _mtime_cache, _map_cache

    role_map_file = _resolve_role_map_path()

    try:
        mtime = os.path.getmtime(role_map_file)
    except OSError:
        if _map_cache is None:
            logger.error("角色映射文件不存在: %s，所有角色将判为缺失", role_map_file)
        return _map_cache if _map_cache is not None else {}

    if _map_cache is not None and _mtime_cache == mtime:
        return _map_cache

    try:
        with open(role_map_file, "rb") as f:
            data = tomllib.load(f)
        result: dict[str, tuple[str | None, str]] = {}
        for entry in data.get("role", []):
            key = entry.get("key")
            if not key:
                continue
            tag = entry.get("target_tag", "")
            result[key] = (tag if tag else None, entry.get("display", key))
        _mtime_cache = mtime
        _map_cache = result
        return result
    except Exception as e:
        logger.error(
            "角色映射文件解析失败 %s: %s，沿用上次缓存（无缓存则全部判为缺失）",
            role_map_file, e,
        )
        return _map_cache if _map_cache is not None else {}


def _resolve_role_map_path() -> Path:
    """解析 role_map.toml 路径，支持 LYRA_ROLE_MAP_FILE 环境变量覆盖。"""
    env = os.environ.get("LYRA_ROLE_MAP_FILE", "").strip()
    if env:
        return Path(env)
    return _ROLE_MAP_FILE


def _resolve_base_url() -> str:
    """解析 credits 爬取用的根地址。

    优先级：LYRA_CREDITS_BASE_URL 环境变量 > 默认 CF Worker 代理。
    """
    env = os.environ.get("LYRA_CREDITS_BASE_URL", "").strip()
    return env if env else _DEFAULT_CREDITS_BASE_URL


# ---------------------------------------------------------------------------
# 网页爬取
# ---------------------------------------------------------------------------


def _normalize_region(region: str) -> str:
    """规范化 region：小写、去 language 后缀。

    zh-Hans-CN → cn, zh-Hant-TW → tw, en-US → us
    """
    r = (region or "us").strip().lower()
    if "-" in r:
        r = r.rsplit("-", 1)[-1].lower()
    return r if r else "us"


async def _fetch_single_region(
    song_id: str,
    region: str,
    *,
    client: httpx.AsyncClient,
    base_url: str,
) -> dict[str, Any] | None:
    """爬取单个 region 的 credits 网页。

    返回值：
    - dict: API 兼容格式的制作人员数据
    - _NO_CREDITS_SENTINEL: 有效真实页但无 roleNames（永久无 credits）
    - None: 失败（网络/落地页/结构异常等临时失败）
    """
    r = _normalize_region(region)
    url = f"{base_url}/{r}/song/{song_id}?_={random.randint(1, 999999)}"

    try:
        response = await client.get(url, headers=_CREDITS_HEADERS, follow_redirects=True)
    except httpx.HTTPError as e:
        logger.debug("Credits: 网络请求失败 (%s/%s): %s", r, song_id, e)
        return None

    if response.status_code != 200:
        logger.debug(
            "Credits: 网页访问失败 (ID: %s): HTTP %d", song_id, response.status_code,
        )
        return None

    # 落地页守卫：200 但 song_id 不在 HTML = 异常页（geo-redirect 复现 /
    # CF 边缘缓存错页）。显式记 WARNING + 返回 None，让上层 region fallback
    # 探测其他区，全失败则标 failed——避免被静默吞成"无 credits"。
    if song_id not in response.text:
        logger.warning(
            "Credits: 命中异常页（非真实歌曲页）region=%s "
            "status=%d body_len=%d (ID: %s) — "
            "疑似 geo-redirect 复现或 CF 边缘缓存错页",
            r, response.status_code, len(response.text), song_id,
        )
        return None

    soup = BeautifulSoup(response.content, "html.parser")
    script_tag = soup.find("script", id="serialized-server-data")
    if not script_tag or not script_tag.string:
        logger.debug("Credits: 未找到数据脚本 (ID: %s)", song_id)
        return None

    try:
        json_data = json.loads(script_tag.string)
    except (json.JSONDecodeError, TypeError) as e:
        logger.debug("Credits: JSON 解析失败 (ID: %s): %s", song_id, e)
        return None

    try:
        sections = json_data["data"][0]["data"]["sections"]
    except (KeyError, IndexError, TypeError) as e:
        logger.debug("Credits: 数据结构解析失败 (ID: %s): %s", song_id, e)
        return None

    # 松验证：检查是否为有效歌曲页面
    is_valid_page = any(
        s.get("id") == "songDetail" or s.get("itemKind") == "songDetailHeader"
        for s in sections
    )
    if not is_valid_page:
        logger.debug(
            "Credits: 未识别到标准歌曲页面结构，尝试继续提取 (ID: %s)", song_id,
        )

    # 遍历 sections 找含 roleNames 的 items → 构建 API 兼容格式
    api_style_data: dict[str, list[dict[str, Any]]] = {"data": []}
    for section in sections:
        items = section.get("items", [])
        has_role_data = any(
            isinstance(item, dict) and item.get("roleNames")
            for item in items
        )
        if not has_role_data:
            continue

        title = section.get("title", section.get("id", "unknown"))
        relationships: dict[str, dict[str, list[dict[str, Any]]]] = {
            "credit-artists": {"data": []},
        }

        for item in items:
            if not isinstance(item, dict):
                continue
            relationships["credit-artists"]["data"].append({
                "id": "web_" + str(item.get("name", "unknown")),
                "attributes": {
                    "name": item.get("name"),
                    "roleNames": item.get("roleNames", []),
                },
            })

        api_style_data["data"].append({
            "attributes": {"title": title, "kind": section.get("id", "")},
            "relationships": relationships,
        })

    # 如果没有提取到任何含 roleNames 的数据：
    # - is_valid_page=True → 永久无 credits，返回哨兵
    # - is_valid_page=False → 疑似缓存精简版，返回 None 让上层 fallback
    if not api_style_data["data"]:
        if is_valid_page:
            logger.debug(
                "Credits: 有效真实页但无 roleNames，判定为永久无 credits "
                "(region=%s, ID: %s)", r, song_id,
            )
            return _NO_CREDITS_SENTINEL
        logger.debug(
            "Credits: 页面未含制作人员数据，可能是缓存精简版 (ID: %s)", song_id,
        )
        return None

    return api_style_data


async def fetch_credits(
    song_id: str,
    primary_region: str = "us",
    *,
    client: httpx.AsyncClient | None = None,
    base_url: str | None = None,
) -> dict[str, Any] | None:
    """爬取 Apple Music 制作人员信息，含串行 region fallback。

    Args:
        song_id: Apple Music Song ID。
        primary_region: 首选区域（如 us/cn/jp）。
        client: 可选 httpx.AsyncClient（供测试注入）。
        base_url: 可选 credits 爬取根地址。

    Returns:
        - dict: API 兼容格式的制作人员数据
        - _NO_CREDITS_SENTINEL: 永久无 credits
        - None: 全 region 失败
    """
    resolved_base = base_url or _resolve_base_url()
    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=15.0)

    try:
        # 先试 primary region
        result = await _fetch_single_region(
            song_id, primary_region, client=client, base_url=resolved_base,
        )

        # 哨兵：永久无 credits，无需 fallback
        if result is not None and _is_sentinel_check(result):
            logger.info(
                "Credits: primary region '%s' 确认无制作人员数据（永久），"
                "跳过探测 (ID: %s)", primary_region, song_id,
            )
            return result

        # primary 成功
        if result is not None:
            return result

        # primary 失败 → 串行 fallback
        primary_norm = _normalize_region(primary_region)
        candidates = [r for r in _DEFAULT_FALLBACK_REGIONS if r != primary_norm]

        if candidates:
            cand_disp = ",".join(candidates)
            logger.info(
                "Credits: primary region '%s' 无数据，开始串行探测 %s (ID: %s)",
                primary_region, cand_disp, song_id,
            )

        for cand_region in candidates:
            await asyncio.sleep(API_DELAY)
            result = await _fetch_single_region(
                song_id, cand_region, client=client, base_url=resolved_base,
            )

            # 哨兵：永久无 credits
            if result is not None and _is_sentinel_check(result):
                logger.info(
                    "Credits: region '%s' 确认无制作人员数据（永久）(ID: %s)",
                    cand_region, song_id,
                )
                return result

            # 命中
            if result is not None:
                logger.info(
                    "Credits: region 探测命中 '%s' (ID: %s)", cand_region, song_id,
                )
                return result

        # 全 region 失败
        logger.warning(
            "Credits: 所有 region 均无数据 (ID: %s)", song_id,
        )
        return None
    finally:
        if should_close:
            await client.aclose()


def _is_sentinel_check(data: dict[str, Any] | None) -> bool:
    """检查是否为 _NO_CREDITS_SENTINEL。"""
    return data is not None and data.get("__no_credits__") is True


# ---------------------------------------------------------------------------
# 映射 + 聚合
# ---------------------------------------------------------------------------


def process_credits_data(
    json_data: dict[str, Any] | None,
) -> tuple[dict[str, list[str]] | None, set[str]]:
    """解析 JSON，按 role_map 映射为 authoritative_fields。

    Args:
        json_data: fetch_credits 返回的 dict（非哨兵）。

    Returns:
        (authoritative_fields, missing_roles)
        - authoritative_fields: 语义字段名 → list[str]，哨兵/无效输入时为 None
        - missing_roles: 未定义的 roleName 集合
    """
    if json_data is None or _is_sentinel_check(json_data):
        return None, set()

    if not json_data or "data" not in json_data:
        return None, set()

    # 初始化 tags：各标准角色 set + performer 聚合 dict
    tags: dict[str, set[str]] = {
        "composer": set(),
        "lyricist": set(),
        "producer": set(),
        "mixer": set(),
        "engineer": set(),
        "remixer": set(),
        "arranger": set(),
        "conductor": set(),
        "djmixer": set(),
    }
    performer_dict: dict[str, set[str]] = {}  # name → set[english_role_name]
    missing_roles: set[str] = set()

    role_map = get_role_map()

    for category in json_data["data"]:
        try:
            artists = category["relationships"]["credit-artists"]["data"]
        except (KeyError, TypeError):
            continue

        for art in artists:
            try:
                name = art["attributes"]["name"]
                roles = art["attributes"].get("roleNames", [])
            except (KeyError, TypeError):
                continue

            if not name:
                continue

            if name not in performer_dict:
                performer_dict[name] = set()

            for role_name in roles:
                if role_name not in role_map:
                    missing_roles.add(role_name)
                    continue

                target_tag, english_role_name = role_map[role_name]

                # A. 存入 performer 聚合（使用英文名）
                performer_dict[name].add(english_role_name)

                # B. 如果有 target_tag，存入对应标准角色标签
                if target_tag and target_tag in tags:
                    tags[target_tag].add(name)

    # 构建 authoritative_fields
    authoritative_fields: dict[str, list[str]] = {}

    # 标准角色字段
    for field, values in tags.items():
        if values:
            authoritative_fields[field] = sorted(values)

    # performer 聚合："姓名 (角色1, 角色2)" 格式，去重
    performer_list: list[str] = []
    for name, roles in performer_dict.items():
        roles_str = ", ".join(sorted(roles))
        performer_list.append(f"{name} ({roles_str})")
    if performer_list:
        authoritative_fields["performer"] = sorted(performer_list)

    if not authoritative_fields:
        return None, missing_roles

    return authoritative_fields, missing_roles


# ---------------------------------------------------------------------------
# 公共入口
# ---------------------------------------------------------------------------


async def get_credits(
    song_id: str,
    primary_region: str = "us",
    *,
    client: httpx.AsyncClient | None = None,
    base_url: str | None = None,
) -> dict[str, Any] | None:
    """一站式：爬取 + 映射，返回 authoritative_fields 或哨兵或 None。

    Args:
        song_id: Apple Music Song ID。
        primary_region: 首选区域。
        client: 可选 httpx.AsyncClient（供测试注入）。
        base_url: 可选 credits 爬取根地址。

    Returns:
        - dict[str, list[str]]: authoritative_fields（语义字段名 → list[str]）
        - _NO_CREDITS_SENTINEL: 永久无 credits（dict[str, bool]）
        - None: 全 region 失败
    """
    json_data = await fetch_credits(
        song_id, primary_region, client=client, base_url=base_url,
    )

    # 哨兵直接透传
    if json_data is not None and _is_sentinel_check(json_data):
        return _NO_CREDITS_SENTINEL

    # None → 全 region 失败
    if json_data is None:
        return None

    # 有效数据 → 映射
    authoritative_fields, missing_roles = process_credits_data(json_data)

    if missing_roles:
        logger.warning(
            "Credits: 缺失角色 %s，已知角色仍会返回。"
            "补全 data/role_map.toml 后重扫 (ID: %s)",
            sorted(missing_roles), song_id,
        )

    return authoritative_fields
