"""Lyra FastAPI 应用入口。

创建 app、注册路由、配置 CORS、启动校验。
"""

import asyncio
import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.index.progress import ScannerProgress, set_progress
from backend.index.scanner import Scanner, set_scanner
from backend.index.store import IndexStore, set_store
from backend.index.watcher import Watcher
from backend.play.stream import play_router
from backend.server.apple_routes import apple_router
from backend.server.credits_routes import credits_router
from backend.server.library_routes import library_router
from backend.server.meta_routes import meta_router
from backend.server.routes import router as api_router
from backend.server.scanner_routes import scanner_router

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
app.include_router(library_router, prefix="/api")
app.include_router(scanner_router, prefix="/api")
app.include_router(play_router, prefix="/api")
app.include_router(meta_router, prefix="/api")
app.include_router(credits_router, prefix="/api")
app.include_router(apple_router, prefix="/api")

# ---------------------------------------------------------------------------
# 模块级资源引用（shutdown 时使用）
# ---------------------------------------------------------------------------

_watcher: Watcher | None = None
_initial_scan_task: asyncio.Task[None] | None = None


# ---------------------------------------------------------------------------
# Startup event
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def on_startup() -> None:
    """启动校验：检查音乐库根配置状态 + 初始化数据库 schema + 启动 watcher。

    不因配置缺失/路径不存在而 raise 终止进程——
    让进程起来，健康检查暴露状态，便于排障。
    """
    global _watcher, _initial_scan_task
    settings = get_settings()

    # -- 音乐库根校验（M1 已有逻辑，保留不变） --
    library_root = settings.music_library_root

    if library_root is None:
        logger.warning(
            "LYRA_MUSIC_LIBRARY_ROOT is not set. "
            "Health check will report library as not_configured. "
            "Set this to the music library mount point (e.g. /music)."
        )
    else:
        library_path = settings.music_library_path()
        if library_path is not None and library_path.exists():
            logger.info("Music library root is reachable: %s", library_path)
        else:
            logger.error(
                "LYRA_MUSIC_LIBRARY_ROOT is set to '%s' but the path does not exist. "
                "Health check will report library as unreachable.",
                library_root,
            )

    # -- 数据库 schema 初始化（M2-A1 新增） --
    db_path = settings.db_path_resolved()
    logger.info("Database path resolved: %s", db_path)

    try:
        # 确保父目录存在
        db_path.parent.mkdir(parents=True, exist_ok=True)

        store = IndexStore(db_path)
        await store.init_schema()
        set_store(store)
        logger.info("Database store initialized successfully.")
    except Exception:
        logger.exception(
            "Failed to initialize database at %s. "
            "/api/library will return 503 until the issue is resolved.",
            db_path,
        )
        set_store(None)
        set_progress(None)
        set_scanner(None)
        return

    # -- 扫描进度广播器初始化（A2 新增） --
    progress = ScannerProgress()
    set_progress(progress)
    logger.info("Scanner progress tracker initialized.")

    # -- 索引扫描器初始化（A2 新增） --
    if library_root is not None and library_path is not None and library_path.exists():
        scanner = Scanner(store, library_path)
        set_scanner(scanner)

        # 注册进度回调：scanner → progress 广播
        async def _on_scan_progress(count: int, folder_count: int) -> None:
            await progress.broadcast(count, folder_count)

        scanner.set_on_progress(_on_scan_progress)  # type: ignore[arg-type]

        # -- 文件监听器初始化（A2 新增） --
        _watcher = Watcher(scanner, library_path)
        await _watcher.start()

        # -- 初始扫描（A2：首次启动异步全量扫描，不阻塞 startup） --
        _initial_scan_task = asyncio.create_task(_initial_scan(scanner, progress))
    else:
        logger.warning(
            "Library root not available — scanner and watcher will not start. "
            "Set LYRA_MUSIC_LIBRARY_ROOT to a reachable directory."
        )
        set_scanner(None)

    # -- Apple WebAPI token 预热（M4-B 新增） --
    try:
        from backend.meta.apple import TokenManager

        tm = TokenManager.get_instance()
        await tm.ensure_token()
        logger.info("Apple WebAPI token pre-fetched successfully.")
    except Exception:
        logger.warning(
            "Apple WebAPI token pre-fetch failed. "
            "Will retry on first request."
        )


async def _initial_scan(scanner: Scanner, progress: ScannerProgress) -> None:
    """首次启动异步全量扫描。

    不阻塞 startup——扫描在后台执行，进度通过 SSE 推送。
    """
    try:
        logger.info("Starting initial scan of library...")
        result = await scanner.scan_all()
        await progress.broadcast_scan_complete(
            result["files_processed"],
            result["folders_processed"],
        )
        logger.info(
            "Initial scan complete: %d files indexed, %d deleted, %d folders",
            result["files_processed"],
            result["files_deleted"],
            result["folders_processed"],
        )
    except Exception:
        logger.exception("Initial scan failed")
        await progress.broadcast_scan_complete(0, 0)


# ---------------------------------------------------------------------------
# Shutdown event
# ---------------------------------------------------------------------------


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """停止文件监听器 + 关闭 Apple WebAPI token client。

    关闭 TokenManager 内部的长连接 httpx.AsyncClient（token 抓取用），
    避免容器正常停止时连接泄漏（§3.6 状态/资源约束）。
    close() 幂等：_client 已为 None 时直接返回。
    """
    global _watcher, _initial_scan_task

    if _initial_scan_task is not None:
        _initial_scan_task.cancel()
        try:
            await _initial_scan_task
        except asyncio.CancelledError:
            pass
        _initial_scan_task = None

    if _watcher is not None:
        await _watcher.stop()
        _watcher = None

    # Apple WebAPI token client 关闭（与 startup 预热对称）
    try:
        from backend.meta.apple import TokenManager

        await TokenManager.get_instance().close()
    except Exception:
        logger.warning("Failed to close Apple WebAPI token client.", exc_info=True)

    logger.info("Lyra shutdown complete.")