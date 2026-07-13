"""Lyra Credits 路由。

端点：
- GET /api/meta/{track_id}/credits?storefront=us — 获取制作人员权威值
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.config import get_settings
from backend.index.store import get_store
from backend.meta.credits import get_credits
from backend.meta.song_id import extract_song_id

logger = logging.getLogger(__name__)

credits_router = APIRouter(tags=["credits"])


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _resolve_track(track_id: str) -> tuple[Path, dict[str, object]]:
    """解析 track_id 并验证路径安全。

    Returns:
        (file_path, row_dict)

    Raises:
        HTTPException:
            422 — 非数字 track_id
            503 — store 未初始化
            404 — track 不存在 / 路径不在库根下 / 文件不存在
    """
    try:
        rowid = int(track_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid track ID")

    store = get_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    row = await store.get_track_by_id(rowid)
    if row is None:
        raise HTTPException(status_code=404, detail="Track not found")

    # 路径安全校验
    track_path = Path(row["path"]).resolve()
    settings = get_settings()
    library_root = settings.music_library_path()
    if library_root is None:
        raise HTTPException(status_code=503, detail="Library root not configured")
    if not track_path.is_relative_to(library_root.resolve()):
        raise HTTPException(status_code=404, detail="Track not found")

    if not track_path.is_file():
        raise HTTPException(status_code=404, detail="Track not found")

    return track_path, dict(row)


# ---------------------------------------------------------------------------
# GET /meta/{track_id}/credits
# ---------------------------------------------------------------------------


@credits_router.get("/meta/{track_id}/credits")
async def credits_fetch(track_id: str, storefront: str = "us") -> dict[str, object]:
    """获取制作人员权威值。

    从 track 的 tag_map 读取 Apple Music Song ID，
    爬取 Apple Music 网页版制作人员信息，
    按 role_map.toml 映射为 authoritative_fields。

    Returns:
        - 200 + authoritative_fields: 制作人员权威值
        - 200 + {"no_credits": true}: 永久无 credits（哨兵）
        - 400: song_id 不在标签中
        - 404: track 不存在
        - 503: 全 region 失败 / store 未初始化
    """
    _, row = await _resolve_track(track_id)

    # 解析 tag_map（与 apple_routes 对齐：无效 JSON / 非 dict → 空 dict）
    tag_map_str: str = str(row.get("tag_map") or "{}")
    try:
        tag_map = json.loads(tag_map_str)
    except (json.JSONDecodeError, TypeError):
        tag_map = {}
    if not isinstance(tag_map, dict):
        tag_map = {}

    # 提取 song_id（收敛口径：cnID → freeform songId → 大小写不敏感兜底）
    song_id = extract_song_id(tag_map)
    if song_id is None:
        raise HTTPException(
            status_code=400,
            detail="No Apple Music Song ID found in track tags",
        )

    # 爬取 + 映射
    result = await get_credits(song_id, storefront)

    # 哨兵：永久无 credits
    if result is not None and result.get("__no_credits__") is True:
        return {"no_credits": True}

    # 全 region 失败
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="Failed to fetch credits from all regions",
        )

    # 成功：返回 authoritative_fields
    return {"track_id": track_id, "authoritative_fields": result}
