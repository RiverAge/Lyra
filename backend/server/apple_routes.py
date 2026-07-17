"""Lyra Apple 元数据拉取路由。

端点：
- GET /api/meta/{track_id}/apple — 从 Apple WebAPI 拉取权威元数据
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import get_settings
from backend.index.store import get_store
from backend.meta.apple import AppleAPIError, get_song_info
from backend.meta.song_id import extract_song_id
from backend.meta.writer import read_tag_map

logger = logging.getLogger(__name__)

apple_router = APIRouter(tags=["apple"])


# ---------------------------------------------------------------------------
# 响应模型
# ---------------------------------------------------------------------------


class AppleFetchResponse(BaseModel):
    """GET /api/meta/{track_id}/apple 响应。"""

    track_id: str
    song_id: str
    storefront: str
    lang: str
    authoritative_fields: dict[str, list[str]]


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _resolve_track(track_id: str) -> tuple[Path, dict[str, object]]:
    """解析 track_id 并验证路径安全。

    复用 meta_routes._resolve_track 模式：
    - 422 — 非数字 track_id
    - 503 — store 未初始化 / library root 未配置
    - 404 — track 不存在 / 路径不在库根下 / 文件不存在

    Returns:
        (file_path, row_dict)
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
# GET /meta/{track_id}/apple
# ---------------------------------------------------------------------------


@apple_router.get("/meta/{track_id}/apple", response_model=AppleFetchResponse)
async def apple_fetch(
    track_id: str,
    storefront: str = "us",
    lang: str = "zh-Hans",
) -> AppleFetchResponse:
    """从 Apple WebAPI 拉取权威元数据。

    流程：
    1. _resolve_track 验证 track_id + 路径安全
    2. 现读文件 tag_map 读 song_id（cnID / songId freeform，B 方案不入库）
    3. song_id 不在标签 → 400
    4. 调 apple.get_song_info 拉取权威元数据
    5. 返回 authoritative_fields

    错误码：
    - 400 — song_id 不在标签（无法拉取，需先有 Apple song_id）
    - 404 — track 不存在 / Apple API 404（歌曲不存在）
    - 422 — 非数字 track_id
    - 503 — store 未初始化 / token 抓取失败
    """
    track_path, _ = await _resolve_track(track_id)

    # 现读文件 tag_map（B 方案：不入库，按需读）
    try:
        tag_map, _codec = read_tag_map(track_path)
    except (ValueError, Exception):
        tag_map = {}

    # 提取 song_id
    song_id = extract_song_id(tag_map)
    if song_id is None:
        raise HTTPException(
            status_code=400,
            detail="No Apple song_id found in track tags (cnID or songId)",
        )

    # 拉取权威元数据
    try:
        authoritative_fields = await get_song_info(song_id, storefront, lang)
    except AppleAPIError as e:
        if e.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Song not found on Apple Music: {e}",
            )
        raise HTTPException(
            status_code=503,
            detail=f"Apple API error: {e}",
        )
    except Exception as e:
        logger.exception("Unexpected error fetching Apple metadata for song %s", song_id)
        raise HTTPException(
            status_code=503,
            detail=f"Failed to fetch Apple metadata: {e}",
        )

    return AppleFetchResponse(
        track_id=track_id,
        song_id=song_id,
        storefront=storefront,
        lang=lang,
        authoritative_fields=authoritative_fields,
    )
