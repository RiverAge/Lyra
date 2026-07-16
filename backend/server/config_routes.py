"""Lyra 配置只读路由——config 端点。

端点：
- GET /api/config — 返回运行期环境配置（只读，环境变量驱动，运行期不可改）

设计：
- 纯只读：暴露 LYRA_* 环境变量解析后的值，供设置页"环境信息"区展示
- 不提供写端点：环境变量在进程启动时定型，运行期改无意义（改了也不生效）
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from backend.config import get_settings

logger = logging.getLogger(__name__)

config_router = APIRouter(tags=["config"])


@config_router.get("/config")
async def get_config() -> dict:
    """运行期环境配置（只读）。

    所有值来自 LYRA_* 简单环境变量（BaseSettings 解析）。
    music_library_root / static_dir / log_dir 可能为 None（未配置）。

    Returns:
        {music_library_root, db_path, static_dir, log_level, log_dir,
         log_max_bytes, log_backup_count, library_configured}
        library_configured: music_library_root 是否已配置（非 None）。
    """
    s = get_settings()
    return {
        "music_library_root": s.music_library_root,
        "db_path": s.db_path,
        "static_dir": s.static_dir,
        "log_level": s.log_level,
        "log_dir": s.log_dir,
        "log_max_bytes": s.log_max_bytes,
        "log_backup_count": s.log_backup_count,
        "library_configured": s.music_library_root is not None,
    }
