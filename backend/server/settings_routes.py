"""Lyra settings 路由。

端点：
- GET /api/settings — 读取应用配置
- PUT /api/settings — 更新应用配置

配置项持久化在 SQLite app_settings 表（单行 id=1），Web UI 读写。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.index.store import get_store

logger = logging.getLogger(__name__)

settings_router = APIRouter(prefix="/settings", tags=["settings"])


class AppSettingsPayload(BaseModel):
    """PUT /settings 请求体。credits_base_url 空字符串=直连 music.apple.com。"""

    credits_base_url: str = ""


class AppSettingsResponse(BaseModel):
    """GET/PUT /settings 响应体。"""

    credits_base_url: str
    updated_at: int


@settings_router.get("", response_model=AppSettingsResponse)
async def get_settings() -> AppSettingsResponse:
    """读取应用配置。

    store 未初始化或首次启动（app_settings 无行）时返空值默认，
    不报错——前端能在配置页看到空输入框并填写。
    """
    store = get_store()
    if store is None:
        return AppSettingsResponse(credits_base_url="", updated_at=0)
    row = await store.get_app_settings()
    if row is None:
        return AppSettingsResponse(credits_base_url="", updated_at=0)
    return AppSettingsResponse(
        credits_base_url=row["credits_base_url"] or "",
        updated_at=row["updated_at"],
    )


@settings_router.put("", response_model=AppSettingsResponse)
async def update_settings(payload: AppSettingsPayload) -> AppSettingsResponse:
    """更新应用配置（覆盖写）。

    credits_base_url 会 strip 首尾空白。空字符串=直连 music.apple.com。
    """
    store = get_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    cleaned = payload.credits_base_url.strip()
    await store.set_app_settings(credits_base_url=cleaned)
    logger.info("App settings updated: credits_base_url=%r", cleaned or "(direct connect)")

    row = await store.get_app_settings()
    # row 必非 None（刚 set 过）
    assert row is not None, "app_settings row missing after set"
    return AppSettingsResponse(
        credits_base_url=row["credits_base_url"],
        updated_at=row["updated_at"],
    )
