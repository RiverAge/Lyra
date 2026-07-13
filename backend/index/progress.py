"""Lyra 扫描进度推送。

FastAPI StreamingResponse SSE 实现 + 轮询端点支持。
只发累计 count（不预估 total），限流广播（攒 0.5s 或每 50 文件发一次）。
状态真源是 SQLite scanner_status 表（§3.6）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 限流常量
# ---------------------------------------------------------------------------

_MIN_BROADCAST_INTERVAL = 0.5  # 秒
_MIN_FILE_GAP = 50  # 至少 50 个文件变更后才广播


# ---------------------------------------------------------------------------
# ScannerProgress
# ---------------------------------------------------------------------------


class ScannerProgress:
    """扫描进度广播器。

    管理 SSE 客户端连接 + 限流广播 + 状态查询。
    """

    def __init__(self) -> None:
        # 已连接的 SSE 客户端队列
        self._clients: list[asyncio.Queue[str]] = []
        self._last_broadcast_time: float = 0.0
        self._last_broadcast_count: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()

    # ---- SSE 客户端管理 ----

    def register(self) -> asyncio.Queue[str]:
        """注册一个 SSE 客户端。

        Returns:
            该客户端专属的 asyncio.Queue，用于发送 SSE 事件。
        """
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        self._clients.append(queue)
        logger.debug("SSE 客户端已连接 (当前连接数: %d)", len(self._clients))
        return queue

    def unregister(self, queue: asyncio.Queue[str]) -> None:
        """注销一个 SSE 客户端。"""
        try:
            self._clients.remove(queue)
        except ValueError:
            pass
        logger.debug("SSE 客户端已断开 (当前连接数: %d)", len(self._clients))

    # ---- 广播 ----

    async def broadcast(self, count: int, folder_count: int) -> None:
        """限流广播扫描进度到所有连接的 SSE 客户端。

        同时更新 SQLite scanner_status 表（作为进度真源）。

        Args:
            count: 当前累计已扫文件数。
            folder_count: 当前累计已扫 folder 数。
        """
        # 限流判定
        now = time.monotonic()
        should_send = False

        async with self._lock:
            if now - self._last_broadcast_time >= _MIN_BROADCAST_INTERVAL:
                should_send = True
            elif abs(count - self._last_broadcast_count) >= _MIN_FILE_GAP:
                should_send = True

            if should_send:
                self._last_broadcast_time = now
                self._last_broadcast_count = count

        if not should_send:
            return

        # 构建事件
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        data = json.dumps(
            {
                "count": count,
                "folder_count": folder_count,
                "timestamp": now_ms,
            },
            ensure_ascii=False,
        )
        message = f"data: {data}\n\n"

        # 广播到所有客户端（非阻塞清理死连接）
        dead_queues: list[asyncio.Queue[str]] = []
        for queue in self._clients:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # 客户端消费太慢，丢弃本次消息
                pass
            except Exception:
                dead_queues.append(queue)

        for q in dead_queues:
            self.unregister(q)

    async def broadcast_scan_complete(self, count: int, folder_count: int) -> None:
        """扫描完成时强制发送最终事件（不限流）。"""
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        data = json.dumps(
            {
                "count": count,
                "folder_count": folder_count,
                "timestamp": now_ms,
                "state": "completed",
            },
            ensure_ascii=False,
        )
        message = f"data: {data}\n\n"

        dead_queues: list[asyncio.Queue[str]] = []
        for queue in self._clients:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass
            except Exception:
                dead_queues.append(queue)

        for q in dead_queues:
            self.unregister(q)

    # ---- SSE 流生成器 ----

    async def sse_generator(self, queue: asyncio.Queue[str]):
        """SSE 事件流生成器（供 FastAPI StreamingResponse 使用）。

        从 asyncio.Queue 取消息，yield 到 SSE 流。
        """
        # 保活计时器：每 30s 发一次 comment 保持连接
        async def _keepalive() -> None:
            while True:
                await asyncio.sleep(30)
                try:
                    queue.put_nowait(": keepalive\n\n")
                except (asyncio.QueueFull, Exception):
                    break

        keepalive_task = asyncio.create_task(_keepalive())

        try:
            yield "data: {\"type\": \"connected\"}\n\n"

            while True:
                try:
                    msg = await queue.get()
                    yield msg
                except asyncio.CancelledError:
                    break
                except Exception:
                    break
        finally:
            keepalive_task.cancel()
            try:
                await keepalive_task
            except asyncio.CancelledError:
                pass
            self.unregister(queue)


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

_progress: ScannerProgress | None = None


def set_progress(progress: ScannerProgress | None) -> None:
    """设置或清除全局 ScannerProgress 实例。"""
    global _progress
    _progress = progress


def get_progress() -> ScannerProgress | None:
    """获取全局 ScannerProgress 实例。"""
    return _progress