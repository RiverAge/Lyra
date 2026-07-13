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
