"""Lyra API 路由。

所有路由挂在 /api 前缀下（由 main.py include_router 指定），
与前端 http.ts baseURL='/api' → vite proxy → :8000 形成硬契约。
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter

from backend.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    """健康检查端点。

    Returns:
        JSON: status + checked_at (epoch millis) + library_root 可达性。
        不会递归扫描，仅做 Path.exists() 判定。
    """
    settings = get_settings()
    library_root = settings.music_library_root
    library_path = settings.music_library_path()

    if library_root is None:
        library_status = "not_configured"
    elif library_path is not None and library_path.exists():
        library_status = "reachable"
    else:
        library_status = "unreachable"

    now_utc = datetime.now(UTC)
    checked_at_ms = int(now_utc.timestamp() * 1000)

    return {
        "status": "ok",
        "checked_at": checked_at_ms,
        "library": {
            "root": library_root,
            "status": library_status,
        },
    }