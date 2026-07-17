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
    """catch-all：非 /api、非 /assets 路径的兜底。

    两段逻辑：
    1. 若路径对应 static 根下的真实文件（favicon.svg / robots.txt 等
       public/ 产物，build 时拷到 dist 根、不在 assets/ 子目录），直接
       返回该文件——否则会被下面第 2 步当路由返回 index.html，浏览器
       拿 HTML 当 SVG 解析，favicon 出不来。
    2. 否则（前端路由如 /track/123）返 index.html 让 vue-router 接管。

    Args:
        full_path: 路径参数（catch-all 捕获）。

    Returns:
        静态文件 FileResponse / index.html FileResponse / JSONResponse 404。
    """
    settings = get_settings()
    if not settings.static_dir:
        return JSONResponse(
            {"detail": "Static files not configured"},
            status_code=404,
        )

    static_root = Path(settings.static_dir)

    # 1. static 根下的真实文件优先 serve（favicon.svg 等 public 产物）。
    #    防路径穿越：解析后必须仍在 static_root 内（挡 ../etc/passwd 之类）。
    if full_path:
        candidate = (static_root / full_path).resolve()
        try:
            candidate.relative_to(static_root.resolve())
        except ValueError:
            return JSONResponse({"detail": "Not found"}, status_code=404)
        if candidate.is_file():
            return FileResponse(candidate)

    # 2. 非文件路径（前端路由）→ 返 index.html 让 vue-router 接管
    index_path = static_root / "index.html"
    if not index_path.exists():
        return JSONResponse(
            {"detail": "index.html not found"},
            status_code=404,
        )

    return FileResponse(index_path, media_type="text/html")
