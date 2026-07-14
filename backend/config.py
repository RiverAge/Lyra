"""Lyra 配置层。

所有配置项统一 LYRA_ 前缀，由环境变量注入。不写死任何物理路径。
"""

import logging
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 日志级别合法值（与 stdlib logging 一致）
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    """Lyra 应用配置。

    所有配置项从环境变量读取，前缀 LYRA_。例如：
      LYRA_MUSIC_LIBRARY_ROOT=/music
      LYRA_DB_PATH=/data/lyra.db
      LYRA_LOG_DIR=/logs
      LYRA_LOG_LEVEL=DEBUG
    """

    model_config = SettingsConfigDict(
        env_prefix="LYRA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    music_library_root: str | None = None
    """音乐库根路径。

    由部署配置决定（如容器内 /music，本机 Y:\\music）。
    None 表示未配置（健康检查应明确反映此状态）。
    """

    db_path: str = "./data/lyra.db"
    """数据库文件路径。

    支持相对路径（相对于工作目录）或绝对路径。
    默认值 ./data/lyra.db 适用于从仓库根目录启动 uvicorn 的场景。
    部署时通过 LYRA_DB_PATH 环境变量覆盖（如 /data/lyra.db）。
    """

    static_dir: str | None = None
    """前端静态产物目录（Vite build 产物）。

    None = 不 serve 静态文件（本机开发态，前端走 vite dev server）。
    生产容器内为 /app/static（Dockerfile COPY dist → /app/static）。
    配置后 main.py 会 mount /assets + 注册 SPA fallback 路由。
    """

    # ---- 日志配置 ----

    log_level: str = "INFO"
    """日志级别。

    合法值：DEBUG / INFO / WARNING / ERROR / CRITICAL。
    非法值静默降级为 INFO（pydantic validator 处理）。
    影响 lyra 根 logger 及所有子 logger（backend.*）。
    """

    log_dir: str | None = None
    """日志文件落盘目录。

    None = 不落盘，仅 stdout（本机开发默认）。
    配置后在该目录下生成 lyra.log，按大小 rotate。
    Docker 部署推荐挂载卷（如 -v /host/logs:/logs，设 LYRA_LOG_DIR=/logs）。
    目录不存在时自动创建（mkdir -p）；创建失败降级为仅 stdout + warning。
    """

    log_max_bytes: int = 10 * 1024 * 1024
    """单个日志文件最大字节数（rotate 阈值）。

    默认 10MB。达到此大小后 rotate 为 lyra.log.1, lyra.log.2, ...。
    """

    log_backup_count: int = 5
    """保留的 rotate 备份文件数量。

    默认 5。超出后最老的备份文件被删除。
    """

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v: str | None) -> str:
        """校验日志级别，非法值降级为 INFO。"""
        if v is None:
            return "INFO"
        level = v.strip().upper()
        if level not in _VALID_LOG_LEVELS:
            # 静默降级，不抛异常（防配置 typo 导致进程无法启动）
            return "INFO"
        return level

    def music_library_path(self) -> Path | None:
        """将配置字符串转为 pathlib.Path。

        Returns:
            Path 实例，若未配置则返回 None。
        """
        if self.music_library_root is None:
            return None
        return Path(self.music_library_root)

    def db_path_resolved(self) -> Path:
        """将 db_path 解析为绝对路径。

        相对路径以当前工作目录为基准 resolve。

        Returns:
            解析后的绝对 Path。
        """
        return Path(self.db_path).resolve()

    def log_level_int(self) -> int:
        """将 log_level 字符串转为 logging 模块整数常量。"""
        return getattr(logging, self.log_level, logging.INFO)


def get_settings() -> Settings:
    """工厂函数，供 FastAPI 依赖注入使用。"""
    return Settings()