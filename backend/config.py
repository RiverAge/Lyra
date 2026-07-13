"""Lyra 配置层。

所有配置项统一 LYRA_ 前缀，由环境变量注入。不写死任何物理路径。
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Lyra 应用配置。

    所有配置项从环境变量读取，前缀 LYRA_。例如：
      LYRA_MUSIC_LIBRARY_ROOT=/music
      LYRA_DB_PATH=/data/lyra.db
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


def get_settings() -> Settings:
    """工厂函数，供 FastAPI 依赖注入使用。"""
    return Settings()