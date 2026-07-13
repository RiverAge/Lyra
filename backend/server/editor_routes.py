"""Lyra 逐字歌词编辑器路由。

端点:
- GET   /api/lyrics/{track_id}/edit — 读 sidecar TTML → parse → 返回 span 结构 JSON
- PATCH /api/lyrics/{track_id}/edit — 改单个 span/line 时间 → 序列化写回
- POST  /api/lyrics/{track_id}/edit — 全量替换(整份 doc)→ 序列化写回

sidecar 路径自算(参考 AGENTS.md §3.3 路径算法,apple 来源默认 <library_root>/.lyrics/
<rel_no_suffix>.ttml,其它来源在 .lyrics/<source>/ 下加 -<source> 后缀)。
二次确认在 UI/M6,本块路由直接执行写。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import get_settings
from backend.index.store import get_store
from backend.lyrics.editor import (
    Line,
    LyricDoc,
    Span,
    parse_ttml,
    serialize_ttml,
    update_line_time,
    update_span_time,
)
from backend.lyrics.sidecar import is_within_lyrics_root, sidecar_path_for

logger = logging.getLogger(__name__)

editor_router = APIRouter(tags=["lyrics-editor"])

# 支持的来源(对齐 AGENTS.md §3.3 sidecar 目录命名)
# apple  → .lyrics/apple/<rel>.ttml(无后缀)
# 其它   → .lyrics/<source>/<rel>-<source>.ttml
_SUPPORTED_SOURCES = {"apple", "netease", "qq"}
_DEFAULT_SOURCE = "apple"


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------


class SpanModel(BaseModel):
    """span 的 JSON 表示。"""

    text: str
    begin_ms: int
    end_ms: int


class LineModel(BaseModel):
    """line 的 JSON 表示。"""

    key: str
    begin_ms: int
    end_ms: int
    spans: list[SpanModel] = []
    text: str = ""


class LyricDocModel(BaseModel):
    """整份 doc 的 JSON 表示(GET 返回 / POST 接收)。"""

    lines: list[LineModel]
    source: str = "netease"


class PatchSpanRequest(BaseModel):
    """PATCH 改单个 span 时间。line_index+span_index 二选一定位。

    同时给 line_index+span_index → 改 span;
    只给 line_index(无 span_index)→ 改 line。
    """

    line_index: int
    span_index: int | None = None
    begin_ms: int
    end_ms: int


class EditorWriteResponse(BaseModel):
    """PATCH/POST 写回响应。"""

    track_id: str
    source: str
    path: str
    doc: LyricDocModel


# ---------------------------------------------------------------------------
# 辅助:track 解析(复用 _resolve_track 模式:422/503/404/路径安全)
# ---------------------------------------------------------------------------


async def _resolve_track(track_id: str) -> tuple[Path, dict[str, object]]:
    """解析 track_id 并验证路径安全。

    复用 meta_routes._resolve_track 模式:
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
# 辅助:sidecar 路径自算
# ---------------------------------------------------------------------------


def _sidecar_path(track_path: Path, library_root: Path, source: str) -> Path:
    """计算 sidecar TTML 路径,复用 sidecar.sidecar_path_for(单一真源)。

    路径语义「source 替换 mirror 首段」由 sidecar.py 实现(M5-B 审计确认正确),
    不在此重复实现避免行为分叉。另经 is_within_lyrics_root 校验路径安全。

    apple  → <library_root>/.lyrics/apple/<Artist/Album/song>.ttml
    其它   → <library_root>/.lyrics/<source>/<Artist/Album/song>-<source>.ttml
    """
    path = sidecar_path_for(track_path, library_root, source)  # type: ignore[arg-type]
    if not is_within_lyrics_root(path, library_root):
        raise HTTPException(status_code=404, detail="Sidecar path out of bounds")
    return path


# ---------------------------------------------------------------------------
# 辅助:doc ↔ model 转换
# ---------------------------------------------------------------------------


def _doc_to_model(doc: LyricDoc) -> LyricDocModel:
    """LyricDoc → LyricDocModel(JSON 可序列化)。"""
    line_models = [
        LineModel(
            key=line.key,
            begin_ms=line.begin_ms,
            end_ms=line.end_ms,
            spans=[
                SpanModel(text=s.text, begin_ms=s.begin_ms, end_ms=s.end_ms)
                for s in line.spans
            ],
            text=line.text,
        )
        for line in doc.lines
    ]
    return LyricDocModel(lines=line_models, source=doc.source)


def _model_to_doc(model: LyricDocModel) -> LyricDoc:
    """LyricDocModel → LyricDoc。"""
    lines = [
        Line(
            key=lm.key,
            begin_ms=lm.begin_ms,
            end_ms=lm.end_ms,
            spans=[
                Span(text=s.text, begin_ms=s.begin_ms, end_ms=s.end_ms)
                for s in lm.spans
            ],
            text=lm.text,
        )
        for lm in model.lines
    ]
    return LyricDoc(lines=lines, source=model.source)


# ---------------------------------------------------------------------------
# GET /lyrics/{track_id}/edit
# ---------------------------------------------------------------------------


@editor_router.get(
    "/lyrics/{track_id}/edit",
    response_model=LyricDocModel,
)
async def get_edit(track_id: str, source: str = _DEFAULT_SOURCE) -> LyricDocModel:
    """读 sidecar TTML → parse → 返回 span 结构 JSON。

    Args:
        source: 来源(apple/netease/qq),默认 apple

    错误码:
    - 400 — 不支持的 source
    - 404 — track 不存在 / sidecar 不存在
    - 422 — 非数字 track_id
    - 503 — store 未初始化 / library root 未配置
    - 500 — TTML 解析失败
    """
    if source not in _SUPPORTED_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported source '{source}'. Supported: {sorted(_SUPPORTED_SOURCES)}",
        )

    track_path, _ = await _resolve_track(track_id)
    settings = get_settings()
    library_root = settings.music_library_path()
    if library_root is None:
        raise HTTPException(status_code=503, detail="Library root not configured")

    sidecar = _sidecar_path(track_path, library_root, source)
    if not sidecar.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Lyrics sidecar not found: {sidecar}",
        )

    try:
        xml_text = sidecar.read_text(encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to read sidecar: {e}")

    try:
        doc = parse_ttml(xml_text)
    except ValueError as e:
        logger.exception("Failed to parse TTML sidecar %s", sidecar)
        raise HTTPException(status_code=500, detail=f"Failed to parse TTML: {e}")

    return _doc_to_model(doc)


# ---------------------------------------------------------------------------
# PATCH /lyrics/{track_id}/edit
# ---------------------------------------------------------------------------


@editor_router.patch(
    "/lyrics/{track_id}/edit",
    response_model=EditorWriteResponse,
)
async def patch_edit(
    track_id: str,
    req: PatchSpanRequest,
    source: str = _DEFAULT_SOURCE,
) -> EditorWriteResponse:
    """改单个 span/line 时间 → 序列化写回 sidecar。

    body: line_index + (可选 span_index) + begin_ms + end_ms。
    - span_index 给出 → 改该 span 的 begin/end
    - span_index 为 None → 改该 line 的 begin/end

    错误码:
    - 400 — 不支持的 source / 越界索引(显式)
    - 404 — track 不存在 / sidecar 不存在
    - 422 — 非数字 track_id
    - 503 — store 未初始化 / library root 未配置
    - 500 — 解析/序列化/写盘失败
    """
    if source not in _SUPPORTED_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported source '{source}'. Supported: {sorted(_SUPPORTED_SOURCES)}",
        )

    track_path, _ = await _resolve_track(track_id)
    settings = get_settings()
    library_root = settings.music_library_path()
    if library_root is None:
        raise HTTPException(status_code=503, detail="Library root not configured")

    sidecar = _sidecar_path(track_path, library_root, source)
    if not sidecar.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Lyrics sidecar not found: {sidecar}",
        )

    try:
        xml_text = sidecar.read_text(encoding="utf-8")
        doc = parse_ttml(xml_text)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse TTML: {e}")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to read sidecar: {e}")

    try:
        if req.span_index is not None:
            doc = update_span_time(
                doc,
                req.line_index,
                req.span_index,
                req.begin_ms,
                req.end_ms,
            )
        else:
            doc = update_line_time(
                doc,
                req.line_index,
                req.begin_ms,
                req.end_ms,
            )
    except IndexError as e:
        raise HTTPException(status_code=400, detail=f"Index out of range: {e}")

    try:
        new_xml = serialize_ttml(doc)
    except Exception as e:
        logger.exception("Failed to serialize TTML for track %s", track_id)
        raise HTTPException(status_code=500, detail=f"Failed to serialize TTML: {e}")

    try:
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(new_xml, encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to write sidecar: {e}")

    return EditorWriteResponse(
        track_id=track_id,
        source=source,
        path=str(sidecar),
        doc=_doc_to_model(doc),
    )


# ---------------------------------------------------------------------------
# POST /lyrics/{track_id}/edit
# ---------------------------------------------------------------------------


@editor_router.post(
    "/lyrics/{track_id}/edit",
    response_model=EditorWriteResponse,
)
async def post_edit(
    track_id: str,
    body: LyricDocModel,
) -> EditorWriteResponse:
    """全量替换:整份 doc → 序列化写回 sidecar(覆盖)。

    body: 完整 LyricDocModel(含 source)。路径目标由 body.source 决定——
    全量替换语义下,写入的 doc 的 source 即目标 sidecar 来源(单一真源,
    不再额外接 query source 避免歧义)。

    错误码:
    - 400 — 不支持的 source
    - 404 — track 不存在
    - 422 — 非数字 track_id
    - 503 — store 未初始化 / library root 未配置
    - 500 — 序列化/写盘失败
    """
    doc = _model_to_doc(body)
    source = doc.source
    if source not in _SUPPORTED_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported source '{source}'. Supported: {sorted(_SUPPORTED_SOURCES)}",
        )

    track_path, _ = await _resolve_track(track_id)
    settings = get_settings()
    library_root = settings.music_library_path()
    if library_root is None:
        raise HTTPException(status_code=503, detail="Library root not configured")

    sidecar = _sidecar_path(track_path, library_root, source)

    try:
        new_xml = serialize_ttml(doc)
    except Exception as e:
        logger.exception("Failed to serialize TTML for track %s", track_id)
        raise HTTPException(status_code=500, detail=f"Failed to serialize TTML: {e}")

    try:
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(new_xml, encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to write sidecar: {e}")

    return EditorWriteResponse(
        track_id=track_id,
        source=source,
        path=str(sidecar),
        doc=_doc_to_model(doc),
    )
