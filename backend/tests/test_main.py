"""测试——main.py lifespan shutdown 资源清理。

迁移自原 on_shutdown 测试：lifespan 的 shutdown 段抽成 _run_shutdown 函数，
测试直接调用它，验证：
1. cancel initial_scan_task
2. stop watcher
3. close TokenManager httpx client

不跑 lifespan startup 段（startup 依赖 config/store/scanner/watcher 全链路，
已在 test_scanner/test_library 间接覆盖，单独测需大量 mock）。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend import main

pytestmark = pytest.mark.asyncio


class TestRunShutdown:
    """_run_shutdown 资源清理测试（等价迁移自 TestOnShutdown）。"""

    async def test_shutdown_closes_token_manager(self) -> None:
        """shutdown 调用 TokenManager.get_instance().close()。

        容器正常停止时 httpx.AsyncClient 长连接必须关闭，防泄漏。
        """
        mock_tm = MagicMock()
        mock_tm.close = AsyncMock()

        with patch(
            "backend.meta.apple.TokenManager.get_instance",
            return_value=mock_tm,
        ):
            await main._run_shutdown(watcher=None, initial_scan_task=None)

        mock_tm.close.assert_awaited_once()

    async def test_shutdown_cancels_initial_scan_task(self) -> None:
        """shutdown 取消 initial_scan_task（已存在的清理行为，不应回归）。"""

        async def _hang_forever() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise

        task = asyncio.create_task(_hang_forever())

        mock_tm = MagicMock()
        mock_tm.close = AsyncMock()

        with patch(
            "backend.meta.apple.TokenManager.get_instance",
            return_value=mock_tm,
        ):
            await main._run_shutdown(watcher=None, initial_scan_task=task)

        assert task.cancelled() or task.done()
        mock_tm.close.assert_awaited_once()

    async def test_shutdown_stops_watcher(self) -> None:
        """shutdown 停止 watcher（已存在的清理行为，不应回归）。"""
        mock_watcher = MagicMock()
        mock_watcher.stop = AsyncMock()

        mock_tm = MagicMock()
        mock_tm.close = AsyncMock()

        with patch(
            "backend.meta.apple.TokenManager.get_instance",
            return_value=mock_tm,
        ):
            await main._run_shutdown(
                watcher=mock_watcher,  # type: ignore[arg-type]
                initial_scan_task=None,
            )

        mock_watcher.stop.assert_awaited_once()

    async def test_shutdown_idempotent_no_resources(self) -> None:
        """无 watcher / initial_scan_task 时 shutdown 不报错。

        TokenManager.close() 幂等：_client 为 None 时直接返回，
        不应抛异常。
        """
        from backend.meta.apple import TokenManager

        TokenManager.reset_instance()
        await main._run_shutdown(watcher=None, initial_scan_task=None)
        TokenManager.reset_instance()

    async def test_shutdown_tolerates_close_exception(self) -> None:
        """close() 抛异常时 shutdown 不 re-raise（吞掉，记 warning）。"""
        mock_tm = MagicMock()
        mock_tm.close = AsyncMock(side_effect=RuntimeError("close failed"))

        with patch(
            "backend.meta.apple.TokenManager.get_instance",
            return_value=mock_tm,
        ):
            # 不应抛异常
            await main._run_shutdown(watcher=None, initial_scan_task=None)

        mock_tm.close.assert_awaited_once()
