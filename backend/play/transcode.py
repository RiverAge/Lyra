"""Lyra 播放层——实时转码（ffmpeg subprocess → Opus in Ogg）。

对浏览器不可解码的 codec（如 ALAC），通过 ffmpeg 实时转码为 Opus 流式输出。
浏览器原生可解码的 codec 不经此模块，走 stream.py 的 Range 直传。

设计约束：
- 用 stdlib subprocess 直控 ffmpeg，不引入 pydub/ffmpeg-python 等封装
- 不写临时文件，走 stdout pipe
- ffmpeg 进程生命周期与 HTTP 请求绑定：客户端断开 → kill 进程
- 启动时探测 ffmpeg 可用性，不可用时转码请求返回 503

实现说明（Windows 兼容）：
- 用同步 `subprocess.Popen` 而非 `asyncio.create_subprocess_exec`。
  原因：uvicorn 在 Windows 上运行于 `SelectorEventLoop`，而 SelectorEventLoop
  不支持子进程 transport（`create_subprocess_exec` 会抛 `NotImplementedError`）。
  同步 `subprocess.Popen` 不依赖 event loop 的 subprocess transport，跨平台稳。
- ffmpeg stdout 的阻塞式 `read()` 放后台线程，通过 thread-safe 的 asyncio.Queue
  桥接回主协程，避免阻塞 event loop。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import threading
from collections.abc import AsyncGenerator
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 浏览器原生可解码的 codec 白名单——这些走 Range 直传，不转码
NATIVE_CODECS: frozenset[str] = frozenset({
    "mp3",
    "flac",
    "aac",
    "opus",
    "vorbis",
    "wav",
})

# 转码输出格式
TRANSCODE_CONTENT_TYPE = "audio/ogg"
TRANSCODE_CODEC = "libopus"
TRANSCODE_FORMAT = "ogg"

# ffmpeg 读取分块大小（64 KB，比文件流大以减少 syscall 开销）
_CHUNK_SIZE = 64 * 1024

# ---------------------------------------------------------------------------
# ffmpeg 可用性探测
# ---------------------------------------------------------------------------

# 模块级缓存：None = 未探测，True/False = 探测结果
_ffmpeg_available: bool | None = None


def probe_ffmpeg() -> bool:
    """探测 ffmpeg 二进制是否可用（shutil.which）。

    结果缓存在模块级变量，只探一次。
    """
    global _ffmpeg_available  # noqa: PLW0603
    if _ffmpeg_available is None:
        _ffmpeg_available = shutil.which("ffmpeg") is not None
        if _ffmpeg_available:
            logger.info("ffmpeg found — transcoding available for non-native codecs")
        else:
            logger.warning(
                "ffmpeg not found — transcoding unavailable. "
                "ALAC and other non-native codecs will return 503."
            )
    return _ffmpeg_available


def is_ffmpeg_available() -> bool:
    """返回缓存的 ffmpeg 可用性（不重复探测）。"""
    if _ffmpeg_available is None:
        return probe_ffmpeg()
    return _ffmpeg_available


def reset_ffmpeg_probe() -> None:
    """重置探测缓存（仅测试用）。"""
    global _ffmpeg_available  # noqa: PLW0603
    _ffmpeg_available = None


# ---------------------------------------------------------------------------
# 转码流生成器
# ---------------------------------------------------------------------------


async def transcode_stream(
    file_path: Path,
) -> AsyncGenerator[bytes, None]:
    """通过 ffmpeg 将音频文件实时转码为 Opus in Ogg，流式输出。

    用同步 `subprocess.Popen` 启动 ffmpeg（非 `asyncio.create_subprocess_exec`，
    后者在 Windows uvicorn 的 SelectorEventLoop 下抛 NotImplementedError）。
    stdout 阻塞 read 放后台线程，经 asyncio.Queue（call_soon_threadsafe 投递）
    桥接回主协程 yield，不阻塞 event loop。

    客户端断开时的进程清理：Starlette 的 StreamingResponse 在 send() 抛
    OSError（客户端断开，spec>=2.4）时终止迭代 body_iterator，生成器被
    异常关闭，触发本函数的 finally 块 → proc.kill() + proc.wait()。
    不依赖轮询 disconnect 信号（原 _DisconnectWatcher 机制已删，见审计 P2-1）。

    Args:
        file_path: 原始音频文件路径。

    Yields:
        bytes: ffmpeg stdout 输出的 Opus/Ogg 数据块。
    """
    proc = subprocess.Popen(
        ["ffmpeg",
         "-i", str(file_path),
         "-c:a", TRANSCODE_CODEC,
         "-f", TRANSCODE_FORMAT,
         "-v", "error",
         "pipe:1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    loop = asyncio.get_running_loop()
    # 主协程消费队列：放 bytes 块，None = 生产端结束哨兵
    queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=256)

    def _produce() -> None:
        """后台线程：阻塞读 ffmpeg stdout，投递到主协程队列。"""
        try:
            while True:
                chunk = proc.stdout.read(_CHUNK_SIZE)
                if not chunk:
                    break
                loop.call_soon_threadsafe(queue.put_nowait, chunk)
        except Exception:
            logger.exception("ffmpeg stdout 读取线程异常")
        finally:
            # 哨兵：通知主协程生产结束（无论正常 EOF 还是异常）
            try:
                loop.call_soon_threadsafe(queue.put_nowait, None)
            except RuntimeError:
                # loop 已关闭（进程退出时可能发生），忽略
                pass

    producer_thread = threading.Thread(
        target=_produce, name="ffmpeg-stdout-reader", daemon=True,
    )
    producer_thread.start()

    try:
        while True:
            chunk = await queue.get()
            if chunk is None:
                # 哨兵：生产端结束
                break
            yield chunk
    finally:
        # 确保进程被清理（同步，不 await）
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        # 回收生产端线程（kill 后 stdout.read 返回空 → 线程退出）
        producer_thread.join(timeout=5.0)

        # 读 stderr（转码结束才读一次，量极小，-v error 抑制噪声）
        # 放 executor 避免同步阻塞（正常为空，异常时有诊断信息）
        stderr = await loop.run_in_executor(None, proc.stderr.read)
        if stderr:
            stderr_text = stderr.decode(errors="replace").strip()
            if proc.returncode != 0:
                logger.error(
                    "ffmpeg exited with code %d: %s",
                    proc.returncode, stderr_text,
                )
            elif stderr_text:
                logger.debug("ffmpeg stderr: %s", stderr_text)
