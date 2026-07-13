"""Lyra scanner API 路由。

提供：
- GET  /api/scanner/progress — SSE 流（前端 EventSource 订阅）
- GET  /api/scanner/status   — 轮询 JSON（不订阅 SSE 的场景）
- POST /api/scanner/trigger  — 手动触发全量扫描
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.config import get_settings
from backend.index.progress import get_progress
from backend.index.store import get_store

logger = logging.getLogger(__name__)

scanner_router = APIRouter()


# ---------------------------------------------------------------------------
# SSE 进度流
# ---------------------------------------------------------------------------


@scanner_router.get("/scanner/progress")
async def scanner_progress():
    """SSE 扫描进度流。

    前端通过 EventSource 订阅，接收限流后的 count 事件。
    同时发送初始状态（从 scanner_status 表读当前状态，断线重连可恢复）。

    Returns:
        text/event-stream SSE 流。
    """
    progress = get_progress()
    store = get_store()

    if progress is None or store is None:
        raise HTTPException(status_code=503, detail="Scanner not initialized")

    queue = progress.register()

    async def _stream():
        """SSE 生成器包装——先发初始状态，再发实时事件。"""
        try:
            # 初始状态：从 scanner_status 表读当前进度（断线重连可恢复）
            status = await store.get_scanner_status()
            if status is not None:
                now_ms = int(datetime.now(UTC).timestamp() * 1000)
                init_data = json.dumps(
                    {
                        "type": "init",
                        "state": status["state"],
                        "count": status["count"],
                        "folder_count": status["folder_count"],
                        "timestamp": now_ms,
                    },
                    ensure_ascii=False,
                )
                yield f"data: {init_data}\n\n"

            # 实时事件
            async for msg in progress.sse_generator(queue):
                yield msg
        except asyncio.CancelledError:
            pass
        finally:
            progress.unregister(queue)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Nginx 禁用缓冲
        },
    )


# ---------------------------------------------------------------------------
# 轮询状态
# ---------------------------------------------------------------------------


@scanner_router.get("/scanner/status")
async def scanner_status():
    """轮询扫描状态。

    从 SQLite scanner_status 表读取，不依赖 SSE 连接。
    若表为空（首次启动未扫描），返回默认 idle 状态。

    Returns:
        JSON: {"state": "idle|scanning|error", "count": N,
               "folder_count": F, "started_at": ms|null,
               "last_scanned_at": ms|null, "error_message": str|null,
               "library_root": str|null, "library_configured": bool}
    """
    settings = get_settings()
    store = get_store()

    library_root = settings.music_library_root
    library_configured = library_root is not None

    if store is None:
        # DB 未初始化 → 返回基本信息
        return {
            "state": "not_initialized",
            "count": 0,
            "folder_count": 0,
            "started_at": None,
            "last_scanned_at": None,
            "error_message": None,
            "library_root": library_root,
            "library_configured": library_configured,
        }

    row = await store.get_scanner_status()

    if row is None:
        return {
            "state": "idle",
            "count": 0,
            "folder_count": 0,
            "started_at": None,
            "last_scanned_at": None,
            "error_message": None,
            "library_root": library_root,
            "library_configured": library_configured,
        }

    return {
        "state": row["state"],
        "scan_type": row["scan_type"],
        "count": row["count"],
        "folder_count": row["folder_count"],
        "started_at": row["started_at"],
        "last_scanned_at": row["last_scanned_at"],
        "error_message": row["error_message"],
        "library_root": library_root,
        "library_configured": library_configured,
    }


# ---------------------------------------------------------------------------
# 手动触发扫描
# ---------------------------------------------------------------------------


@scanner_router.post("/scanner/trigger")
async def scanner_trigger():
    """手动触发全量扫描。

    该端点不等待扫描完成，立即返回 202。
    扫描在后台异步执行，进度通过 SSE / status 轮询获取。

    Returns:
        202: {"message": "scan triggered", "state": "scanning"}
        503: scanner 未初始化
        409: 扫描已在进行中
    """
    from backend.index.scanner import get_scanner as _get_scanner

    scanner = _get_scanner()
    store = get_store()

    if scanner is None or store is None:
        raise HTTPException(status_code=503, detail="Scanner not initialized")

    # 检查是否已在扫描中
    status = await store.get_scanner_status()
    if status is not None and status["state"] == "scanning":
        raise HTTPException(status_code=409, detail="Scanner is already running")

    # 后台执行
    asyncio.create_task(_run_scan(scanner))

    return {
        "message": "Scan triggered",
        "state": "scanning",
    }


async def _run_scan(scanner: object) -> None:
    """后台执行全量扫描。"""
    try:
        # scanner is actually a Scanner instance; use Any to bypass type narrowing
        s: Any = scanner
        await s.scan_all()
    except Exception:
        logger.exception("手动触发全量扫描失败")
