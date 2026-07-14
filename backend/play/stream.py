"""Lyra 播放层——静态音频流 + HTTP Range 支持 + 实时转码。

端点：GET /api/play/{track_id} 和 HEAD /api/play/{track_id}

分流策略：
- 浏览器原生可解码 codec（mp3/flac/aac/opus/vorbis/wav）→ Range 直传（不变）
- 不可解码 codec（如 alac）→ ffmpeg 实时转码为 Opus in Ogg 流式输出
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.responses import StreamingResponse

from backend.config import get_settings
from backend.index.store import get_store
from backend.play.transcode import (
    NATIVE_CODECS,
    TRANSCODE_CONTENT_TYPE,
    is_ffmpeg_available,
    transcode_stream,
)

logger = logging.getLogger(__name__)

play_router = APIRouter()

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# codec → Content-Type 映射（scanner 入库的 codec 值见 scanner.py:145-153）
_CODEC_CONTENT_TYPE: dict[str, str] = {
    "alac": "audio/mp4",
    "flac": "audio/flac",
    "mp3": "audio/mpeg",
}
_DEFAULT_CONTENT_TYPE = "application/octet-stream"

# 流式读取分块大小（16 KB）
_CHUNK_SIZE = 16 * 1024


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _get_content_type(codec: str | None) -> str:
    """按 codec 推断 Content-Type，未知/None 退化到 octet-stream。"""
    if codec is None:
        return _DEFAULT_CONTENT_TYPE
    return _CODEC_CONTENT_TYPE.get(codec, _DEFAULT_CONTENT_TYPE)


def _parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    """解析 HTTP Range header 的 bytes= 语法。

    Args:
        range_header: Range 请求头值（如 "bytes=0-99"）。
        file_size: 文件总字节数。

    Returns:
        (start, end) 闭区间字节位置（含两端）。

    Raises:
        HTTPException 416: 范围不满足（无效语法 / 越界）。
    """
    if not range_header.startswith("bytes="):
        raise HTTPException(status_code=416, detail="Invalid range header")

    range_value = range_header[6:].strip()

    if not range_value or "-" not in range_value:
        raise HTTPException(status_code=416, detail="Invalid range header")

    start_str, end_str = range_value.split("-", 1)
    start_str = start_str.strip()
    end_str = end_str.strip()

    try:
        if start_str == "":
            # 后缀范围：bytes=-suffix
            suffix = int(end_str)
            if suffix <= 0:
                raise HTTPException(status_code=416, detail="Invalid range")
            start = max(0, file_size - suffix)
            end = file_size - 1
        elif end_str == "":
            # 开区间：bytes=start-
            start = int(start_str)
            if start >= file_size:
                raise HTTPException(status_code=416, detail="Range not satisfiable")
            end = file_size - 1
        else:
            # 闭区间：bytes=start-end
            start = int(start_str)
            end = int(end_str)
            if start >= file_size or end < start:
                raise HTTPException(status_code=416, detail="Range not satisfiable")
            end = min(end, file_size - 1)
    except ValueError:
        raise HTTPException(status_code=416, detail="Invalid range header")

    return start, end


def _file_streamer(file_path: Path, start: int, end: int) -> Generator[bytes, None, None]:
    """按字节范围流式读取文件。

    同步生成器——Starlette 的 StreamingResponse 会在线程池中执行。
    """
    with open(file_path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk_size = min(_CHUNK_SIZE, remaining)
            data = f.read(chunk_size)
            if not data:
                break
            remaining -= len(data)
            yield data


async def _resolve_track(track_id: str) -> tuple[Path, int, str, str | None]:
    """解析 track_id 并验证路径安全。

    Returns:
        (file_path, file_size, content_type, codec)

    Raises:
        HTTPException:
            422 — 非数字 track_id
            503 — store 未初始化 / library_root 未配置
            404 — track 不存在 / 路径不在库根下 / 文件不存在
    """
    # ---- 非数字校验 ----
    try:
        rowid = int(track_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid track ID")

    # ---- store 初始化 ----
    store = get_store()
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Database not initialized",
        )

    # ---- 查库 ----
    row = await store.get_track_by_id(rowid)
    if row is None:
        raise HTTPException(status_code=404, detail="Track not found")

    # ---- 路径安全校验 ----
    track_path = Path(row["path"]).resolve()
    settings = get_settings()
    library_root = settings.music_library_path()
    if library_root is None:
        raise HTTPException(
            status_code=503,
            detail="Library root not configured",
        )
    if not track_path.is_relative_to(library_root.resolve()):
        raise HTTPException(status_code=404, detail="Track not found")

    # ---- 文件存在性 ----
    if not track_path.is_file():
        raise HTTPException(status_code=404, detail="Track not found")

    file_size = track_path.stat().st_size
    codec = row["codec"]
    content_type = _get_content_type(codec)

    return track_path, file_size, content_type, codec


# ---------------------------------------------------------------------------
# GET /play/{track_id}
# ---------------------------------------------------------------------------


@play_router.get("/play/{track_id}")
async def stream_track(request: Request, track_id: str) -> Response:
    """音频流端点——按 codec 分流。

    - 浏览器原生可解码 codec → 无 Range: 200 + 完整文件流; 有 Range: 206
    - 不可解码 codec（如 alac）→ ffmpeg 实时转码为 Opus in Ogg，200 流式输出
    - HEAD 由 `stream_track_head` 处理
    """
    track_path, file_size, content_type, codec = await _resolve_track(track_id)

    # ---- 转码分流 ----
    if codec is not None and codec not in NATIVE_CODECS:
        # 不可解码 → 实时转码
        if not is_ffmpeg_available():
            raise HTTPException(
                status_code=503,
                detail=f"ffmpeg not available, cannot transcode {codec}",
            )

        return StreamingResponse(
            transcode_stream(track_path),
            status_code=200,
            media_type=TRANSCODE_CONTENT_TYPE,
            headers={
                "Cache-Control": "no-cache",
            },
        )

    # ---- 原生可解码 → Range 直传（逻辑不变） ----
    range_header = request.headers.get("range")

    if range_header:
        start, end = _parse_range(range_header, file_size)
        content_length = end - start + 1
        return StreamingResponse(
            _file_streamer(track_path, start, end),
            status_code=206,
            media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(content_length),
                "Accept-Ranges": "bytes",
            },
        )

    return StreamingResponse(
        _file_streamer(track_path, 0, file_size - 1),
        status_code=200,
        media_type=content_type,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
        },
    )


# ---------------------------------------------------------------------------
# HEAD /play/{track_id}
# ---------------------------------------------------------------------------


@play_router.head("/play/{track_id}")
async def stream_track_head(request: Request, track_id: str) -> Response:
    """HEAD 请求：返回与 GET 相同的 header，不返 body。

    转码流无法预知 Content-Length，HEAD 返回 Content-Type + Cache-Control。
    原生可解码格式保留原有 Range 逻辑。
    """
    track_path, file_size, content_type, codec = await _resolve_track(track_id)

    # ---- 转码分流 ----
    if codec is not None and codec not in NATIVE_CODECS:
        if not is_ffmpeg_available():
            raise HTTPException(
                status_code=503,
                detail=f"ffmpeg not available, cannot transcode {codec}",
            )
        return Response(
            status_code=200,
            media_type=TRANSCODE_CONTENT_TYPE,
            headers={
                "Cache-Control": "no-cache",
            },
        )

    # ---- 原生可解码 → Range 直传 header ----
    range_header = request.headers.get("range")

    if range_header:
        start, end = _parse_range(range_header, file_size)
        content_length = end - start + 1
        return Response(
            status_code=206,
            media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(content_length),
                "Accept-Ranges": "bytes",
            },
        )

    return Response(
        status_code=200,
        media_type=content_type,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
        },
    )


# ---------------------------------------------------------------------------
# 转码辅助
# ---------------------------------------------------------------------------
# transcode_stream 直接作为 StreamingResponse body_iterator。
# 客户端断开清理：send OSError → 生成器异常终止 → transcode_stream finally 块
# → proc.kill()。无需 disconnect 轮询（原 _DisconnectWatcher 已删，见审计 P2-1）。