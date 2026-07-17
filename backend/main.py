"""Lyra FastAPI 应用入口。

创建 app、注册路由、启动校验、lifespan 资源管理。

生产态：mount StaticFiles("/assets") + SPA fallback 路由，
单容器同源 serve 前端产物（由 LYRA_STATIC_DIR 配置控制）。
本机开发态：static_dir=None，前端走 vite dev server（:5173），
vite.config.ts 的 proxy /api → :8000 解耦前后端。
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend._version import get_version
from backend.config import get_settings
from backend.index.progress import ScannerProgress, set_progress
from backend.index.scanner import Scanner, set_scanner
from backend.index.store import IndexStore, set_store
from backend.index.watcher import Watcher
from backend.log_setup import AccessLogMiddleware, configure_logging
from backend.play.stream import play_router
from backend.server.apple_routes import apple_router
from backend.server.config_routes import config_router
from backend.server.credits_routes import credits_router
from backend.server.editor_routes import editor_router
from backend.server.library_routes import library_router
from backend.server.lyrics_match_routes import lyrics_router as lyrics_match_router
from backend.server.lyrics_sidecar_routes import lyrics_sidecar_router
from backend.server.meta_routes import meta_router
from backend.server.routes import router as api_router
from backend.server.scanner_routes import scanner_router
from backend.server.settings_routes import settings_router
from backend.server.static_routes import router as static_router

# ---- 日志初始化（必须在所有 logger 使用之前） ----
_settings = get_settings()
configure_logging(_settings)

# 模块级 logger
logger = logging.getLogger("lyra")

# 启动 initial_scan 的冷却时间：距上次扫完未满此值则跳过启动扫描。
# 原因：每次 git pull/重启都重扫 2 万文件 stat + folder hash 计算，即使全
# hash 命中也要 190s（ZFS bind mount stat 慢）。但启动 = 不可能在扫，上次
# 扫完未满 5 分钟说明数据是新的，没必要重扫——watcher 增量扫会捡漏。
# 手动触发（POST /scanner/trigger）不受此冷却影响（用户显式要扫）。
_INITIAL_SCAN_COOLDOWN_MS = 5 * 60 * 1000  # 5 分钟

# ---------------------------------------------------------------------------
# lifespan（替代 deprecated @app.on_event）
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]  # noqa: ANN201
    """应用生命周期：启动初始化 + 停止清理。

    启动逻辑（原 startup event 等价迁移，行为不变）：
    1. 校验音乐库根配置（不因缺失而 raise，靠 /api/health 暴露状态）
    2. 初始化 SQLite schema + store 注入
    3. 启动扫描进度广播器
    4. 启动 scanner + watcher + 后台初始扫描（非阻塞）
    5. 预热 Apple WebAPI token

    停止逻辑（原 shutdown event 等价迁移）：
    1. cancel 初始扫描 task
    2. stop watcher
    3. close Apple token httpx client
    """
    # ---- startup ----
    settings = get_settings()
    library_root = settings.music_library_root

    # -- 音乐库根校验 --
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

    # -- 数据库 schema 初始化 --
    db_path = settings.db_path_resolved()
    logger.info("Database path resolved: %s", db_path)

    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        store = IndexStore(db_path)
        await store.init_schema()
        # 孤儿状态恢复：上次进程被强杀时 state 可能卡在 scanning，
        # 进程刚启动强制置回 idle（否则手动触发会被 409）。自动续扫
        # 不受影响，但孤儿态期间手动按钮失效——见 store.clear_orphan_scanning_state。
        await store.clear_orphan_scanning_state()
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
        # schema 失败时跳过 scanner/watcher/token 初始化，但进程继续运行
        yield
        return

    # -- 扫描进度广播器初始化 --
    progress = ScannerProgress()
    set_progress(progress)
    logger.info("Scanner progress tracker initialized.")

    # -- 索引扫描器初始化 --
    watcher: Watcher | None = None
    initial_scan_task: asyncio.Task[None] | None = None

    if library_root is not None and library_path is not None and library_path.exists():
        scanner = Scanner(store, library_path)
        set_scanner(scanner)

        # 注册进度回调：scanner → progress 广播
        async def _on_scan_progress(count: int, folder_count: int, total: int) -> None:
            await progress.broadcast(count, folder_count, total)

        scanner.set_on_progress(_on_scan_progress)

        # -- 文件监听器初始化 --
        watcher = Watcher(scanner, library_path, store)
        await watcher.start()

        # -- 初始扫描（非阻塞） --
        initial_scan_task = asyncio.create_task(_initial_scan(scanner, progress))
    else:
        logger.warning(
            "Library root not available — scanner and watcher will not start. "
            "Set LYRA_MUSIC_LIBRARY_ROOT to a reachable directory."
        )
        set_scanner(None)

    # -- Apple WebAPI token 预热（后台异步，不阻塞 startup） --
    # ensure_token 要打 3-4 个 HTTPS 到 music.apple.com（大陆网络 3s+），
    # 同步 await 会拖慢 startup。改后台 task：首次请求时若还没取到，
    # TokenManager 自己会等/重试（已有 will retry on first request 兜底）。
    async def _prefetch_apple_token() -> None:
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

    asyncio.create_task(_prefetch_apple_token())

    # -- ffmpeg 可用性探测 --
    try:
        from backend.play.transcode import probe_ffmpeg

        probe_ffmpeg()
    except Exception:
        logger.warning("ffmpeg probe failed.", exc_info=True)

    yield  # ← app 运行期

    # ---- shutdown ----
    await _run_shutdown(watcher, initial_scan_task)


async def _run_shutdown(
    watcher: Watcher | None,
    initial_scan_task: asyncio.Task[None] | None,
) -> None:
    """lifespan shutdown 段：资源清理。

    抽成独立函数便于单元测试（不依赖 lifespan async context manager 驱动）。
    行为与原 on_shutdown 等价：
    1. cancel initial_scan_task（吞 CancelledError）
    2. stop watcher（若非 None）
    3. close Apple token httpx client（异常吞掉记 warning）
    """
    if initial_scan_task is not None:
        initial_scan_task.cancel()
        try:
            await initial_scan_task
        except asyncio.CancelledError:
            pass

    if watcher is not None:
        await watcher.stop()

    # Apple WebAPI token client 关闭（与 startup 预热对称）
    try:
        from backend.meta.apple import TokenManager

        await TokenManager.get_instance().close()
    except Exception:
        logger.warning("Failed to close Apple WebAPI token client.", exc_info=True)

    logger.info("Lyra shutdown complete.")


async def _initial_scan(scanner: Scanner, progress: ScannerProgress) -> None:
    """首次启动异步全量扫描。

    不阻塞 startup——扫描在后台执行，进度通过 SSE 推送。

    冷却：若距上次扫完未满 ``_INITIAL_SCAN_COOLDOWN_MS``，跳过本次启动扫描
    （数据是新的，watcher 增量扫会捡漏）。首次启动（无 last_scanned_at）
    不跳过。手动 trigger 不走这里，不受冷却影响。
    """
    try:
        status = await scanner._store.get_scanner_status()
        last = status["last_scanned_at"] if status else None
        if last:
            elapsed = int(datetime.now(UTC).timestamp() * 1000) - last
            if elapsed < _INITIAL_SCAN_COOLDOWN_MS:
                logger.info(
                    "上次扫描距今 %.1f 分钟（< %d 分钟冷却），跳过 initial_scan",
                    elapsed / 60000,
                    _INITIAL_SCAN_COOLDOWN_MS / 60000,
                )
                return
        logger.info("Starting initial scan of library...")
        result = await scanner.scan_all()
        # 扫描刚写完库，算一次 stats 既塞进完成事件（前端零额外请求拿新
        # 统计），又预热 library_routes 的 stats 缓存（扫完首次 HTTP 也瞬命中）。
        stats = await scanner._store.library_stats()
        from backend.server.library_routes import set_stats_cache

        set_stats_cache(stats)
        await progress.broadcast_scan_complete(
            result["files_processed"],
            result["folders_processed"],
            result["total_files"],
            stats=stats,
        )
        logger.info(
            "Initial scan complete: %d files indexed, %d deleted, %d folders, %d total",
            result["files_processed"],
            result["files_deleted"],
            result["folders_processed"],
            result["total_files"],
        )
    except Exception:
        logger.exception("Initial scan failed")
        await progress.broadcast_scan_complete(0, 0, 0)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Lyra",
    description="音乐元数据与歌词管理 Web 应用",
    version=get_version(),
    lifespan=lifespan,
)

# Access log 中间件（必须在路由注册之前添加，确保所有请求都被记录）
app.add_middleware(AccessLogMiddleware)

# 注册 API 路由 —— /api 前缀是前后端硬契约
app.include_router(api_router, prefix="/api")
app.include_router(library_router, prefix="/api")
app.include_router(scanner_router, prefix="/api")
app.include_router(play_router, prefix="/api")
app.include_router(meta_router, prefix="/api")
app.include_router(credits_router, prefix="/api")
app.include_router(apple_router, prefix="/api")
app.include_router(lyrics_match_router, prefix="/api")
app.include_router(lyrics_sidecar_router, prefix="/api")
app.include_router(editor_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(config_router, prefix="/api")

# ---------------------------------------------------------------------------
# 静态产物 + SPA fallback（生产态）
# ---------------------------------------------------------------------------

if _settings.static_dir:
    _static_path = Path(_settings.static_dir)
    if _static_path.exists() and (_static_path / "assets").exists():
        # 1. mount /assets —— Vite 产物固定子目录（JS/CSS/图片等带 hash 的资产）
        app.mount("/assets", StaticFiles(directory=_static_path / "assets"), name="assets")
        # 2. SPA fallback catch-all —— 必须在所有 /api/* 路由之后注册
        app.include_router(static_router)
        logger.info("Static files mounted at /assets, SPA fallback enabled (dir=%s)", _static_path)
    else:
        logger.warning(
            "LYRA_STATIC_DIR is set to '%s' but the directory or "
            "its 'assets' subdir does not exist. Static files not mounted.",
            _settings.static_dir,
        )
