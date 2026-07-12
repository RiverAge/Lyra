"""Lyra 配置层。

所有配置项统一 LYRA_ 前缀，由环境变量注入。不写死任何物理路径。
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Lyra 应用配置。

    所有配置项从环境变量读取，前缀 LYRA_。例如：
      LYRA_MUSIC_LIBRARY_ROOT=/music
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

    def music_library_path(self) -> Path | None:
        """将配置字符串转为 pathlib.Path。

        Returns:
            Path 实例，若未配置则返回 None。
        """
        if self.music_library_root is None:
            return None
        return Path(self.music_library_root)


def get_settings() -> Settings:
    """工厂函数，供 FastAPI 依赖注入使用。"""
    return Settings()