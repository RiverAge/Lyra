"""Lyra 文件监听器。

watchdog Observer 监听音乐库根，debounce 5s 后触发定点增量扫描。
watch 不支持时静默退化为定时全量扫描 + mtime 对账。

策略抄 Navidrome（§3.5）：
- 事件 channel 缓冲 500
- debounce 平静期 5s，扫描中退避 3×=15s
- 文件事件上溯到父目录作为受影响 folder
- 扫描时检查目录存在性
- 忽略 .DS_Store / dot-folders / $RECYCLE.BIN / #snapshot
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from backend.index.scanner import Scanner
from backend.index.store import IndexStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_DEBOUNCE_SECONDS = 5.0  # §3.5 / O6
_BACKOFF_MULTIPLIER = 3  # 扫描中退避 3× = 15s
_EVENT_QUEUE_SIZE = 500  # §3.5
_PERIODIC_SCAN_INTERVAL = 300  # 退化模式定时扫描间隔（秒）

# ---- watchdog 导入（可选依赖） ----

_HandlerBase: type = object  # _WatchdogHandler 的基类（运行时 = FileSystemEventHandler 或 object）


def _try_init_watchdog() -> bool:
    """尝试导入 watchdog 并设置 _HandlerBase。

    Returns:
        True 如果导入成功，False 如果不可用。
    """
    global _HandlerBase
    try:
        from watchdog.events import FileSystemEventHandler  # noqa: F811

        _HandlerBase = FileSystemEventHandler  # type: ignore[assignment]
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# _WatchdogHandler（延迟绑定基类）
# ---------------------------------------------------------------------------


class _WatchdogHandler(_HandlerBase):  # type: ignore[valid-type,misc]
    """watchdog FileSystemEventHandler。

    将文件事件转为受影响目录，推入 asyncio 队列。
    当 watchdog 可用时继承 FileSystemEventHandler，否则退化为普通 object。
    """

    def __init__(self, queue: asyncio.Queue[Path]) -> None:
        self._queue = queue

    def dispatch(self, event: object) -> None:
        """watchdog 统一入口——覆盖基类 dispatch 拦截所有事件。"""
        src_path = getattr(event, "src_path", None)
        if src_path is None:
            return

        path = Path(src_path)

        # 忽略规则
        if self._should_ignore(path):
            return

        # 文件事件 → 上溯到父目录作为受影响 folder
        if path.is_file() or (not path.exists() and path.suffix):
            folder = path.parent
        elif path.is_dir():
            folder = path
        else:
            folder = path

        # 推入队列（非阻塞，满则丢弃）
        try:
            self._queue.put_nowait(folder)
        except asyncio.QueueFull:
            logger.debug("事件队列满，丢弃事件: %s", folder)

    @staticmethod
    def _should_ignore(path: Path) -> bool:
        """判断路径是否应被忽略。检查路径的所有组成部分。"""
        for part in path.parts:
            if part.startswith("."):
                return True
            if part in ("$RECYCLE.BIN", "#snapshot"):
                return True
        return False


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------


class Watcher:
    """文件系统监听器。

    包装 watchdog Observer，提供 debounce + 定点扫描 + 退化能力。
    """

    def __init__(self, scanner: Scanner, library_root: Path, store: IndexStore) -> None:
        self._scanner = scanner
        self._store = store
        self._library_root = library_root.resolve()
        self._observer: Any = None
        self._queue: asyncio.Queue[Path] = asyncio.Queue(maxsize=_EVENT_QUEUE_SIZE)
        self._debounce_task: asyncio.Task[None] | None = None
        self._periodic_task: asyncio.Task[None] | None = None
        self._watchdog_task: asyncio.Task[None] | None = None
        self._running = False
        self._scanning = False
        self._watch_available = False

    # ---- 公开接口 ----

    async def start(self) -> None:
        """启动文件监听。

        先尝试 watchdog，失败则退化到定时扫描。

        watchdog 的 observer.start()（recursive=True）要递归遍历整个音乐库
        注册 inotify watch——2 万+文件 / 数千 folder 在 ZFS bind mount 上
        实测卡 46 秒，且全程无日志。这不阻塞 startup：watchdog 起没起来不
        影响 API 服务 / 扫描（有 _initial_scan 兜底）。所以 observer 启动
        丢后台 task，start() 立即返回，startup 不再白等。
        """
        if self._running:
            return

        self._running = True

        # watchdog 启动在后台跑（可能慢），不阻塞 startup
        self._watchdog_task = asyncio.create_task(self._start_watchdog())

        # 启动 debounce 循环（watchdog 起来前事件入队也安全，loop 会消费）
        self._debounce_task = asyncio.create_task(self._debounce_loop())

    async def _start_watchdog(self) -> None:
        """后台启动 watchdog observer（可能慢，不阻塞 startup）。

        observer.start() 递归注册 inotify watch 在大库 + ZFS 上慢（数十秒）。
        起来后打日志；失败则置 _watch_available=False 触发退化定时扫描。
        """
        if not _try_init_watchdog():
            self._watch_available = False
            logger.info(
                "Watchdog package not available, falling back to periodic scan every %ds",
                _PERIODIC_SCAN_INTERVAL,
            )
            self._periodic_task = asyncio.create_task(self._periodic_loop())
            return

        try:
            from watchdog.observers import Observer  # noqa: F811

            observer = Observer()
            handler = _WatchdogHandler(self._queue)
            observer.schedule(handler, str(self._library_root), recursive=True)
            observer.start()

            self._observer = observer
            self._watch_available = True
            logger.info(
                "Watcher 已启动 (watchdog), root=%s, debounce=%ss",
                self._library_root,
                _DEBOUNCE_SECONDS,
            )
        except Exception:
            self._watch_available = False
            logger.info(
                "Watcher not supported, falling back to periodic scan every %ds",
                _PERIODIC_SCAN_INTERVAL,
            )
            self._periodic_task = asyncio.create_task(self._periodic_loop())

    async def stop(self) -> None:
        """停止文件监听。"""
        self._running = False

        # 停止 observer
        if self._observer is not None:
            observer = self._observer
            try:
                observer.stop()
                observer.join(timeout=5)
            except Exception:
                logger.warning("停止 watchdog Observer 时异常", exc_info=True)
            self._observer = None

        # 取消任务
        for task in (self._debounce_task, self._periodic_task, self._watchdog_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._debounce_task = None
        self._periodic_task = None
        self._watchdog_task = None

        # 清空队列
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

        logger.info("Watcher 已停止")

    # ---- 内部 ----

    async def _debounce_loop(self) -> None:
        """debounce 主循环。

        流程：
        1. 等待第一个事件（60s 超时防卡死）
        2. 在 debounce 窗口内持续收集事件
        3. 窗口到期 → 去重受影响目录 → 逐个 scan_folder
        4. 若扫描中，等待退避时间后重试
        """
        while self._running:
            try:
                # 等待第一个事件
                folder = await asyncio.wait_for(self._queue.get(), timeout=60.0)
                affected: set[Path] = {folder}

                # debounce 窗口：收集后续事件
                while True:
                    try:
                        folder = await asyncio.wait_for(
                            self._queue.get(),
                            timeout=_DEBOUNCE_SECONDS,
                        )
                        affected.add(folder)
                    except TimeoutError:
                        # 平静期到，退出收集
                        break

                # 去重后扫描
                await self._scan_affected(affected)

            except TimeoutError:
                # 60s 无事件，继续循环
                pass
            except asyncio.CancelledError:
                break

    async def _scan_affected(self, folders: set[Path]) -> None:
        """扫描受影响的目录。

        若当前正在扫描中（watcher 自身重叠，或 scan_all 全量扫描进行中），
        等待退避时间后套娃重试。扫描前检查目录存在性。

        关键：除了 watcher 自身的 ``_scanning`` 标志，还要查 ``scanner_status``
        表的 state——startup 的 ``_initial_scan`` 全量扫描（不经过 watcher 的
        ``_scanning`` 标志）跑时，watcher 若同时增量扫，会和全量扫抢 SQLite
        写锁抛 ``database is locked``（WAL 下读不阻塞写，但写写仍互斥，且默认
        busy_timeout=0 立即报错）。查到 state==scanning 就退避让路。
        """
        if self._scanning:
            await self._backoff_and_retry(folders)
            return

        # 查 DB 级扫描状态（防 watcher 与 scan_all 全量扫抢写锁）
        try:
            status = await self._store.get_scanner_status()
        except Exception:
            logger.debug("查 scanner_status 失败，按非扫描态处理", exc_info=True)
            status = None
        if status is not None and status["state"] == "scanning":
            await self._backoff_and_retry(folders)
            return

        self._scanning = True
        try:
            for folder in sorted(folders, key=str):
                if not self._running:
                    break
                if not folder.exists():
                    logger.debug("目录已不存在，跳过扫描: %s", folder)
                    continue
                try:
                    await self._scanner.scan_folder(folder)
                except Exception:
                    logger.exception("扫描目录失败: %s", folder)
        finally:
            self._scanning = False

    async def _backoff_and_retry(self, folders: set[Path]) -> None:
        """扫描进行中：退避后重试。抽出来让 _scan_affected 可读。"""
        logger.debug(
            "扫描进行中，退避 %ds 后重试 %d 个目录",
            _DEBOUNCE_SECONDS * _BACKOFF_MULTIPLIER,
            len(folders),
        )
        await asyncio.sleep(_DEBOUNCE_SECONDS * _BACKOFF_MULTIPLIER)
        if self._running:
            await self._scan_affected(folders)

    async def _periodic_loop(self) -> None:
        """退化模式：定时全量扫描（仅 watch 不可用时启用）。"""
        while self._running:
            try:
                await asyncio.sleep(_PERIODIC_SCAN_INTERVAL)
                if not self._running:
                    break
                logger.info("退化模式定时全量扫描触发")
                await self._scanner.scan_all()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("退化模式定时扫描异常")