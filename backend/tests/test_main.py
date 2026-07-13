"""测试——main.py 生命周期事件。

P1-2 覆盖：on_shutdown 调用 TokenManager.get_instance().close()，
关闭 token 抓取用的长连接 httpx.AsyncClient，避免容器停止时连接泄漏。

只测 on_shutdown 的资源关闭行为，不测 on_startup（on_startup 依赖
config/store/scanner/watcher 全链路，已在 test_scanner/test_library 间接覆盖，
单独测需要大量 mock，scope 过大）。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from backend import main


class TestOnShutdown:
    """on_shutdown 资源清理测试。"""

    async def test_on_shutdown_closes_token_manager(self) -> None:
        """on_shutdown 调用 TokenManager.get_instance().close()。

        P1-2 修复点：原 main.py 无 on_shutdown 调 close()，
        容器正常停止时 httpx.AsyncClient 长连接泄漏。
        """
        # 确保模块级 _watcher / _initial_scan_task 为 None（无副作用）
        main._watcher = None  # type: ignore[attr-defined]
        main._initial_scan_task = None  # type: ignore[attr-defined]

        mock_tm = MagicMock()
        mock_tm.close = AsyncMock()

        with patch(
            "backend.meta.apple.TokenManager.get_instance",
            return_value=mock_tm,
        ):
            await main.on_shutdown()

        mock_tm.close.assert_awaited_once()

    async def test_on_shutdown_cancels_initial_scan_task(self) -> None:
        """on_shutdown 取消 _initial_scan_task（已存在的清理行为，不应回归）。"""

        async def _hang_forever() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise

        task = asyncio.create_task(_hang_forever())
        main._initial_scan_task = task  # type: ignore[attr-defined]
        main._watcher = None  # type: ignore[attr-defined]

        mock_tm = MagicMock()
        mock_tm.close = AsyncMock()

        with patch(
            "backend.meta.apple.TokenManager.get_instance",
            return_value=mock_tm,
        ):
            await main.on_shutdown()

        assert task.cancelled() or task.done()
        # 任务被清理后模块级引用置空
        assert main._initial_scan_task is None  # type: ignore[attr-defined]
        # close 仍被调用
        mock_tm.close.assert_awaited_once()

    async def test_on_shutdown_stops_watcher(self) -> None:
        """on_shutdown 停止 _watcher（已存在的清理行为，不应回归）。"""
        main._initial_scan_task = None  # type: ignore[attr-defined]

        mock_watcher = MagicMock()
        mock_watcher.stop = AsyncMock()
        main._watcher = mock_watcher  # type: ignore[attr-defined]

        mock_tm = MagicMock()
        mock_tm.close = AsyncMock()

        with patch(
            "backend.meta.apple.TokenManager.get_instance",
            return_value=mock_tm,
        ):
            await main.on_shutdown()

        mock_watcher.stop.assert_awaited_once()
        # watcher 被清理后模块级引用置空
        assert main._watcher is None  # type: ignore[attr-defined]

    async def test_on_shutdown_idempotent_no_resources(self) -> None:
        """无 _watcher / _initial_scan_task 时 on_shutdown 不报错。

        TokenManager.close() 幂等：_client 为 None 时直接返回，
        不应抛异常。
        """
        main._watcher = None  # type: ignore[attr-defined]
        main._initial_scan_task = None  # type: ignore[attr-defined]

        # 用真实 TokenManager 单例（_client 默认为 None，close 幂等返回）
        from backend.meta.apple import TokenManager

        TokenManager.reset_instance()
        await main.on_shutdown()
        # 重置单例避免测试间泄漏
        TokenManager.reset_instance()

    async def test_on_shutdown_tolerates_close_exception(self) -> None:
        """close() 抛异常时 on_shutdown 不 re-raise（吞掉，记 warning）。"""
        main._watcher = None  # type: ignore[attr-defined]
        main._initial_scan_task = None  # type: ignore[attr-defined]

        mock_tm = MagicMock()
        mock_tm.close = AsyncMock(side_effect=RuntimeError("close failed"))

        with patch(
            "backend.meta.apple.TokenManager.get_instance",
            return_value=mock_tm,
        ):
            # 不应抛异常
            await main.on_shutdown()

        mock_tm.close.assert_awaited_once()
