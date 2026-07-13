"""Lyra backend 测试共享 fixtures。

提取共享的 pytest fixtures，供 test_library.py 和 test_scanner.py 使用。
"""

from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI

from backend.index.store import IndexStore, set_store
from backend.server.library_routes import library_router
from backend.server.scanner_routes import scanner_router

# ---------------------------------------------------------------------------
# FastAPI app fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """创建最小 FastAPI app——含 library_router + scanner_router。

    与生产一致：/api 前缀挂载。
    无 startup event，由各测试手动 set_store()。
    """
    app = FastAPI()
    app.include_router(library_router, prefix="/api")
    app.include_router(scanner_router, prefix="/api")
    return app


# ---------------------------------------------------------------------------
# Store fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store(tmp_path: object) -> AsyncGenerator[IndexStore, None]:
    """在临时目录创建已初始化的 IndexStore。

    teardown 时清空模块级单例，防测试间泄漏。
    """
    db_path = tmp_path / "test.db"  # type: ignore[operator]
    store = IndexStore(db_path)  # type: ignore[arg-type]
    await store.init_schema()
    set_store(store)
    yield store
    set_store(None)
