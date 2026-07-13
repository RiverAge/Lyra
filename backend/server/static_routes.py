"""SPA history 模式 fallback 路由。

vue-router 用 createWebHistory()，刷新 /track/123 等非根路径时，
后端必须返回 index.html 让前端路由接管，否则 404。

注册顺序约束（由 main.py 保证）：
- 所有 /api/* 路由先注册 → /api/* 不会走到 catch-all
- /assets 由 StaticFiles mount 占用 → 静态资源不走 catch-all
- 本路由 catch-all `/{full_path:path}` 兜底其余路径，返 index.html

本机开发态（static_dir=None）不注册此路由，前端走 vite dev server。
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from backend.config import get_settings

router = APIRouter()


@router.get("/{full_path:path}", response_model=None)
async def spa_fallback(full_path: str) -> FileResponse | JSONResponse:
    """catch-all：非 /api、非 /assets 路径返回 index.html。

    Args:
        full_path: 路径参数（catch-all 捕获）。

    Returns:
        index.html（FileResponse, text/html）。
        若 static_dir 未配置或 index.html 缺失，返 JSONResponse 404。
    """
    settings = get_settings()
    if not settings.static_dir:
        return JSONResponse(
            {"detail": "Static files not configured"},
            status_code=404,
        )

    index_path = Path(settings.static_dir) / "index.html"
    if not index_path.exists():
        return JSONResponse(
            {"detail": "index.html not found"},
            status_code=404,
        )

    return FileResponse(index_path, media_type="text/html")
