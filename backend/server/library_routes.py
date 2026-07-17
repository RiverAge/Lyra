"""Lyra API 路由——library 端点。"""

import asyncio
import logging
from pathlib import Path

import mutagen  # noqa: PLC0415 — executor 线程内需模块级可用
from fastapi import APIRouter, HTTPException, Query, Response
from mutagen.flac import FLAC as _FLAC  # noqa: PLC0415 — 类型判断用，不直接构造
from mutagen.mp3 import MP3 as _MP3  # noqa: PLC0415
from mutagen.mp4 import MP4 as _MP4  # noqa: PLC0415
from mutagen.mp4 import MP4Cover as _MP4Cover  # noqa: PLC0415 — covr 封面 bytes + format

from backend.config import get_settings
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
    artist: str | None = Query(default=None, description="按艺人模糊匹配"),
    album: str | None = Query(default=None, description="按专辑模糊匹配"),
    codec: str | None = Query(default=None, description="按编码格式精确匹配（如 ALAC）"),
) -> dict:
    """音乐库列表端点。

    从 SQLite 索引读取，支持分页与筛选。

    Args:
        limit: 每页条数，1-500，默认 20。
        offset: 偏移量，>= 0，默认 0。
        artist: 艺人模糊匹配（LIKE），None=不过滤。
        album: 专辑模糊匹配（LIKE），None=不过滤。
        codec: 编码格式精确匹配，None=不过滤。

    Returns:
        {"items": [...], "total": N, "limit": L, "offset": O}
        total 为过滤后的匹配总数（分页页数依据）。空库返 200 + items=[], total=0。

    Raises:
        HTTPException 503: 数据库未初始化。
    """
    store = get_store()
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Database not initialized",
        )

    has_filter = any((artist, album, codec))
    if has_filter:
        total = await store.count_tracks_filtered(
            artist=artist, album=album, codec=codec
        )
        rows = await store.list_tracks_filtered(
            limit=limit, offset=offset, artist=artist, album=album, codec=codec
        )
    else:
        total = await store.count_tracks()
        rows = await store.list_tracks(limit=limit, offset=offset)

    items = [_track_row_to_dict(dict(r)) for r in rows]

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@library_router.get("/library/stats")
async def library_stats() -> dict:
    """曲库聚合统计端点（首页统计卡数据源）。

    Returns:
        {track_count, album_count, total_duration_sec, lossless_ratio}
        lossless_ratio 为 0.0~1.0。空库返回全 0。

    Raises:
        HTTPException 503: 数据库未初始化。
    """
    store = get_store()
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Database not initialized",
        )

    return await store.library_stats()


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


# ---------------------------------------------------------------------------
# GET /library/{track_id}/artwork — 封面图（从音频 tag 现读 bytes）
# ---------------------------------------------------------------------------


def _read_cover_bytes_sync(file_path: Path) -> tuple[bytes, str] | None:
    """同步：用 mutagen 从音频文件读封面 bytes（在 executor 中运行）。

    Returns:
        (cover_bytes, media_type) 或 None（无封面）。
    """
    mf = mutagen.File(str(file_path))
    if mf is None:
        return None

    if isinstance(mf, _MP4):
        covr_list = mf.get("covr")
        if not covr_list:
            return None
        cover = covr_list[0]
        # MP4Cover.imageformat: 0x0d=JPEG, 0x0e=PNG, 0x00=unknown(按 BMP)
        if cover.imageformat == _MP4Cover.FORMAT_PNG:
            media_type = "image/png"
        else:
            media_type = "image/jpeg"
        return bytes(cover), media_type

    if isinstance(mf, _FLAC):
        pictures = mf.pictures
        if not pictures:
            return None
        pic = pictures[0]
        media_type = pic.mime or "image/jpeg"
        return pic.data, media_type

    if isinstance(mf, _MP3):
        for key in mf:
            if not key.startswith("APIC:"):
                continue
            frame = mf[key]
            data = getattr(frame, "data", None)
            if data:
                media_type = getattr(frame, "mime", None) or "image/jpeg"
                return data, media_type
        return None

    return None


def _make_thumbnail_sync(
    cover_bytes: bytes, *, max_width: int = 300,
) -> tuple[bytes, str] | None:
    """同步：ffmpeg 把封面 bytes 压成 JPEG 缩略图（在 executor 中运行）。

    高分辨率原图（实测单张 2-3MB）→ 300px JPEG ~几十 KB。
    列表页一页 20 首封面，原图传输 40-60MB，缩略图后降至 ~1MB。

    Returns:
        (jpeg_bytes, "image/jpeg") 或 None（ffmpeg 不可用/转码失败 → 调用方回退原图）。
    """
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return None  # 容器内 ffmpeg 必有；本机 dev 无则回退原图

    # ffmpeg: stdin pipe 输入原 bytes，scale 到 max_width（保持比例），输出 JPEG。
    # -1 保持高宽比（按 width），jpeg质量 85 视觉无损体积小。
    cmd = [
        ffmpeg, "-i", "pipe:0",
        "-vf", f"scale={max_width}:-1",
        "-q:v", "5",  # JPEG quality 2-31，5 接近视觉无损
        "-f", "image2", "-vcodec", "mjpeg", "pipe:1",
    ]
    try:
        proc = subprocess.run(
            cmd, input=cover_bytes,
            capture_output=True, timeout=10,
        )
    except Exception:
        logger.debug("artwork thumbnail transcode failed", exc_info=True)
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout, "image/jpeg"


@library_router.get("/library/{track_id}/artwork")
async def get_track_artwork(
    track_id: str,
    size: str = Query(
        default="thumb",
        description="thumb=缩略图(300px JPEG,~几十KB,列表用);full=原图",
    ),
) -> Response:
    """封面图端点——从音频文件 tag 现读封面 bytes。

    前端 ``<img src="/api/library/{id}/artwork">`` 直接用。
    has_cover=0 或文件无封面 → 404。

    size=thumb(默认)：ffmpeg 转缩略图(高分辨率原图 2-3MB → 几十 KB)。
    列表页一页 20 首封面，原图传输 40-60MB，缩略图后降至 ~1MB。
    size=full：返回原 bytes（详情页大图用）。

    加 Cache-Control(immutable)：同一封面不重复请求 + 不重复 mutagen 解析。

    Raises:
        HTTPException 422: track_id 非数字。
        HTTPException 404: track 不存在 / 无封面 / 文件缺失。
        HTTPException 503: store 未初始化 / library_root 未配置。
    """
    try:
        rowid = int(track_id)
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid track id: {track_id!r}",
        ) from e

    store = get_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    row = await store.get_track_by_id(rowid)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Track {track_id} not found")

    if not row["has_cover"]:
        raise HTTPException(status_code=404, detail="No cover art")

    # 路径安全校验（照 stream.py _resolve_track 模式）
    track_path = Path(row["path"]).resolve()
    settings = get_settings()
    library_root = settings.music_library_path()
    if library_root is None:
        raise HTTPException(status_code=503, detail="Library root not configured")
    if not track_path.is_relative_to(library_root.resolve()):
        raise HTTPException(status_code=404, detail="Track not found")
    if not track_path.is_file():
        raise HTTPException(status_code=404, detail="Track not found")

    # mutagen 同步调用 → executor
    result = await asyncio.get_event_loop().run_in_executor(
        None, _read_cover_bytes_sync, track_path,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="No cover art")

    cover_bytes, media_type = result

    # 缩略图（默认）：ffmpeg 转，失败回退原图不阻断。
    want_thumb = size != "full"
    if want_thumb:
        thumb = await asyncio.get_event_loop().run_in_executor(
            None, _make_thumbnail_sync, cover_bytes,
        )
        if thumb is not None:
            cover_bytes, media_type = thumb

    # 缓存：封面图内容不变（track id 稳定），immutable 让浏览器长缓存，
    # 列表翻页/刷新不重复请求 artwork，也不重复 mutagen 解析。
    headers = {"Cache-Control": "public, max-age=604800, immutable"}
    return Response(
        content=cover_bytes, media_type=media_type, headers=headers,
    )
