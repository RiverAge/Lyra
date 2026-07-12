"""Lyra FastAPI 应用入口。

创建 app、注册路由、配置 CORS、启动校验。
"""

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.server.routes import router as api_router

# 模块级 logger
logger = logging.getLogger("lyra")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Lyra",
    description="音乐元数据与歌词管理 Web 应用",
    version="0.1.0",
)

# CORS — 允许前端 Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server 默认
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由 —— /api 前缀是前后端硬契约
app.include_router(api_router, prefix="/api")


# ---------------------------------------------------------------------------
# Startup event
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def on_startup() -> None:
    """启动校验：检查音乐库根配置状态。

    不因配置缺失/路径不存在而 raise 终止进程——
    让进程起来，健康检查暴露状态，便于排障。
    """
    settings = get_settings()
    library_root = settings.music_library_root

    if library_root is None:
        logger.warning(
            "LYRA_MUSIC_LIBRARY_ROOT is not set. "
            "Health check will report library as not_configured. "
            "Set this to the music library mount point (e.g. /music)."
        )
        return

    library_path = settings.music_library_path()
    if library_path is not None and library_path.exists():
        logger.info("Music library root is reachable: %s", library_path)
    else:
        logger.error(
            "LYRA_MUSIC_LIBRARY_ROOT is set to '%s' but the path does not exist. "
            "Health check will report library as unreachable.",
            library_root,
        )