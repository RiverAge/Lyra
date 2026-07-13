"""Lyra API 路由——library 端点。"""

import logging

from fastapi import APIRouter, HTTPException, Query

from backend.index.store import get_store

logger = logging.getLogger(__name__)

library_router = APIRouter()


def _track_row_to_dict(row: dict) -> dict:
    """将 DB 行转为 API 响应 dict。

    关键转换：
    - id: int → str（§3.4 ID 字符串契约）
    - has_cover: 保持为 int（0/1），前端按 truthy 使用
    """
    row["id"] = str(row["id"])
    return row


@library_router.get("/library")
async def list_library(
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """音乐库列表端点。

    从 SQLite 索引读取，支持分页。

    Args:
        limit: 每页条数，1-500，默认 20。
        offset: 偏移量，>= 0，默认 0。

    Returns:
        {"items": [...], "total": N, "limit": L, "offset": O}

        空库返 200 + items=[], total=0。

    Raises:
        HTTPException 503: 数据库未初始化。
    """
    store = get_store()
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Database not initialized",
        )

    total = await store.count_tracks()
    rows = await store.list_tracks(limit=limit, offset=offset)

    items = [_track_row_to_dict(dict(r)) for r in rows]

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@library_router.get("/library/{track_id}")
async def get_track(track_id: str) -> dict:
    """单 track 详情端点。

    前端 track 详情页（TrackDetailView）进入时调用，前端用字符串 ID
    （§3.4 ID 字符串契约），此端点解析为 int 后走 store.get_track_by_id。

    Args:
        track_id: track ID（字符串形式的整数主键）。

    Returns:
        track dict（id 转回 str）。

    Raises:
        HTTPException 422: track_id 不是有效整数。
        HTTPException 404: track 不存在。
        HTTPException 503: 数据库未初始化。
    """
    store = get_store()
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Database not initialized",
        )

    try:
        rowid = int(track_id)
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid track id: {track_id!r}",
        ) from e

    row = await store.get_track_by_id(rowid)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Track {track_id} not found",
        )

    return _track_row_to_dict(dict(row))
