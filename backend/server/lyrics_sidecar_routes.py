"""Lyra 歌词 sidecar 路由。

端点：
- GET    /api/lyrics/{track_id}/sidecars          — 列出该 track 所有 sidecar 文件 + 内容
- GET    /api/lyrics/{track_id}/sidecar/{source}  — 读指定来源 sidecar（source = apple/netease/qq）
- DELETE /api/lyrics/{track_id}/sidecar/{source}  — 删除 sidecar
- POST   /api/lyrics/{track_id}/sidecar/{source}  — 手动写入 TTML（body 是 TTML 字符串）

复用 apple_routes/credits_routes 的 _resolve_track 模式（422/503/404/路径安全）。
sidecar 路径额外经 is_within_lyrics_root 校验，防 ``../`` 越出 ``.lyrics/``。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import get_settings
from backend.index.store import get_store
from backend.lyrics.sidecar import (
    Source,
    delete_sidecar,
    is_within_lyrics_root,
    list_sidecars,
    read_sidecar,
    sidecar_path_for,
    write_sidecar,
)

logger = logging.getLogger(__name__)

lyrics_sidecar_router = APIRouter(tags=["lyrics"])

# 路径参数 source 的合法值（apple/netease/qq）。
_VALID_SOURCES: tuple[str, ...] = ("apple", "netease", "qq")


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------


class WriteSidecarRequest(BaseModel):
    """POST sidecar 请求体：TTML 字符串。"""

    content: str


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _resolve_track(track_id: str) -> Path:
    """解析 track_id 并验证路径安全。

    复用 meta_routes._resolve_track 模式：
    - 422 — 非数字 track_id
    - 503 — store 未初始化 / library root 未配置
    - 404 — track 不存在 / 路径不在库根下 / 文件不存在

    Returns:
        track 的绝对文件路径。
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

    track_path = Path(row["path"]).resolve()
    settings = get_settings()
    library_root = settings.music_library_path()
    if library_root is None:
        raise HTTPException(status_code=503, detail="Library root not configured")
    if not track_path.is_relative_to(library_root.resolve()):
        raise HTTPException(status_code=404, detail="Track not found")

    if not track_path.is_file():
        raise HTTPException(status_code=404, detail="Track not found")

    return track_path


def _validate_source(source: str) -> Source:
    """校验 source 参数合法（apple/netease/qq）。非法 → 404。"""
    if source not in _VALID_SOURCES:
        raise HTTPException(status_code=404, detail="Unknown lyric source")
    return source  # type: ignore[return-value]


def _resolve_sidecar_path(track_path: Path, source: Source) -> Path:
    """计算 source 对应的 sidecar 路径 + 路径安全校验。

    越界（不在 ``<library_root>/.lyrics/`` 下）→ 404。
    """
    settings = get_settings()
    library_root = settings.music_library_path()
    if library_root is None:
        raise HTTPException(status_code=503, detail="Library root not configured")
    sidecar_path = sidecar_path_for(track_path, library_root, source)
    if not is_within_lyrics_root(sidecar_path, library_root):
        raise HTTPException(status_code=404, detail="Sidecar path out of bounds")
    return sidecar_path


# ---------------------------------------------------------------------------
# GET /lyrics/{track_id}/sidecars
# ---------------------------------------------------------------------------


@lyrics_sidecar_router.get("/lyrics/{track_id}/sidecars")
async def list_track_sidecars(track_id: str) -> dict[str, object]:
    """列出该 track 的所有 sidecar 文件 + 内容。

    返回 ``{track_id, sidecars: [{source, format, path, content}, ...]}``。
    不存在的 sidecar 不在列表中。
    """
    track_path = await _resolve_track(track_id)
    settings = get_settings()
    library_root = settings.music_library_path()
    if library_root is None:
        raise HTTPException(status_code=503, detail="Library root not configured")
    sidecars = list_sidecars(track_path, library_root)
    return {"track_id": track_id, "sidecars": sidecars}


# ---------------------------------------------------------------------------
# GET /lyrics/{track_id}/sidecar/{source}
# ---------------------------------------------------------------------------


@lyrics_sidecar_router.get("/lyrics/{track_id}/sidecar/{source}")
async def read_track_sidecar(track_id: str, source: str) -> dict[str, object]:
    """读指定来源的 sidecar 内容。

    - 200 + content：存在
    - 404：sidecar 不存在 / source 非法 / 路径越界
    """
    source_valid = _validate_source(source)
    track_path = await _resolve_track(track_id)
    sidecar_path = _resolve_sidecar_path(track_path, source_valid)

    content = read_sidecar(sidecar_path)
    if content is None:
        raise HTTPException(status_code=404, detail="Sidecar not found")

    return {
        "track_id": track_id,
        "source": source,
        "format": "ttml",
        "path": str(sidecar_path),
        "content": content,
    }


# ---------------------------------------------------------------------------
# DELETE /lyrics/{track_id}/sidecar/{source}
# ---------------------------------------------------------------------------


@lyrics_sidecar_router.delete("/lyrics/{track_id}/sidecar/{source}")
async def delete_track_sidecar(track_id: str, source: str) -> dict[str, object]:
    """删除指定来源的 sidecar。

    - 200 + deleted=true：已删除
    - 200 + deleted=false：不存在（幂等删除）
    - 409：apple 默认词不可删（Apple 官方权威主歌词，删了没了；
      要替换应重抓/重下，不从 Lyra UI 删）
    - 404：source 非法 / 路径越界
    """
    source_valid = _validate_source(source)
    if source_valid == "apple":
        raise HTTPException(
            status_code=409,
            detail="Apple 官方歌词不可删除（权威主歌词，请重新抓取/下载覆盖）",
        )
    track_path = await _resolve_track(track_id)
    sidecar_path = _resolve_sidecar_path(track_path, source_valid)

    deleted = delete_sidecar(sidecar_path)
    return {
        "track_id": track_id,
        "source": source,
        "path": str(sidecar_path),
        "deleted": deleted,
    }


# ---------------------------------------------------------------------------
# POST /lyrics/{track_id}/sidecar/{source}
# ---------------------------------------------------------------------------


@lyrics_sidecar_router.post("/lyrics/{track_id}/sidecar/{source}")
async def write_track_sidecar(
    track_id: str, source: str, req: WriteSidecarRequest,
) -> dict[str, object]:
    """手动写入 TTML sidecar（body 是 TTML 字符串）。

    二次确认在 UI（M6 前端），本端点直接提供写能力。

    - 200 + written=true：写入成功
    - 404：source 非法 / 路径越界
    - 503：library root 未配置
    """
    source_valid = _validate_source(source)
    track_path = await _resolve_track(track_id)
    sidecar_path = _resolve_sidecar_path(track_path, source_valid)

    try:
        write_sidecar(sidecar_path, req.content)
    except OSError as e:
        logger.exception("写入 sidecar 失败: %s", sidecar_path)
        raise HTTPException(status_code=500, detail=f"Write failed: {e}") from e

    return {
        "track_id": track_id,
        "source": source,
        "format": "ttml",
        "path": str(sidecar_path),
        "written": True,
    }
