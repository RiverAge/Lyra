"""Lyra 元数据管理路由。

端点：
- POST /api/meta/{track_id}/diff    — 对比本地标签与权威元数据
- POST /api/meta/{track_id}/write   — 写入用户确认后的标签
- GET  /api/meta/fields             — 返回支持的字段映射清单
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import get_settings
from backend.index.store import get_store
from backend.meta.diff import compute_diff
from backend.meta.writer import get_supported_fields, read_tag_map, write_metadata

logger = logging.getLogger(__name__)

meta_router = APIRouter(tags=["meta"])


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------


class DiffRequest(BaseModel):
    authoritative_fields: dict[str, list[str]]


class WriteRequest(BaseModel):
    after_fields: dict[str, list[str]]


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
# GET /meta/fields
# ---------------------------------------------------------------------------


@meta_router.get("/meta/fields")
async def meta_fields() -> dict[str, object]:
    """返回支持的字段映射清单。"""
    return get_supported_fields()


# ---------------------------------------------------------------------------
# POST /meta/{track_id}/diff
# ---------------------------------------------------------------------------


@meta_router.post("/meta/{track_id}/diff")
async def meta_diff(track_id: str, req: DiffRequest) -> dict[str, object]:
    """对比本地标签与权威元数据。

    从 store 取 track 的 tag_map（JSON 反序列化），
    从 body 接收 authoritative_fields，
    调 diff.py compute_diff 产出 before/after 对比结果。
    """
    _, row = await _resolve_track(track_id)

    # 读取 tag_map
    tag_map_str: str = str(row.get("tag_map") or "{}")
    try:
        local_tag_map = json.loads(tag_map_str)
    except (json.JSONDecodeError, TypeError):
        local_tag_map = {}

    if not isinstance(local_tag_map, dict):
        local_tag_map = {}

    result = compute_diff(
        local_tag_map=local_tag_map,  # type: ignore[arg-type]
        auth_fields=req.authoritative_fields,
    )

    return {
        "track_id": track_id,
        "before": result["before"],
        "after": result["after"],
        "diffs": result["diffs"],
    }


# ---------------------------------------------------------------------------
# POST /meta/{track_id}/write
# ---------------------------------------------------------------------------


@meta_router.post("/meta/{track_id}/write")
async def meta_write(track_id: str, req: WriteRequest) -> dict[str, object]:
    """写入用户确认后的标签。

    从 store 取 track 的 path，调 writer.py 写标签，
    写完后读回文件的新 tag_map 返回。
    """
    track_path, row = await _resolve_track(track_id)

    try:
        result = write_metadata(track_path, req.after_fields)
    except (TypeError, ValueError) as e:
        logger.warning("写入标签失败: %s: %s", track_path, e)
        raise HTTPException(status_code=500, detail=f"Write failed: {e}")
    except Exception as e:
        logger.exception("写入标签异常: %s", track_path)
        raise HTTPException(status_code=500, detail=f"Unexpected write error: {e}")

    # 写入后读回新 tag_map
    try:
        new_tag_map, _codec = read_tag_map(track_path)
    except (ValueError, Exception):
        new_tag_map = {}

    return {
        "track_id": track_id,
        "format": result["format"],
        "fields_written": result["fields_written"],
        "new_tag_map": new_tag_map,
    }