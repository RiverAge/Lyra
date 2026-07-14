"""Lyra 日志配置。

职责：
1. 根 logger "lyra" 配置（stdout handler + 可选 RotatingFileHandler）
2. root logger 配置（承接 backend.* 模块，这些模块用 logging.getLogger(__name__)
   命名空间是 backend.xxx，不是 lyra 的子 logger，靠 root 继承输出）
3. lyra.access logger 配置（access log 含 method/path/status/耗时）
4. uvicorn logger 接管（统一格式，禁用原生 access log）
5. 降级逻辑：log_dir 不可写时仅 stdout + warning

设计决策：
- backend.* 模块全部用 logging.getLogger(__name__)，命名空间 backend.xxx，
  不是 lyra 的子 logger。若不配 root，它们传播到未配置的 root（默认 WARNING、
  无 handler、靠 lastResort），导致 LYRA_LOG_LEVEL=DEBUG 对业务模块失效。
  因此 configure_logging 显式配 root logger：设 level + 复用 stdout/file handler，
  backend.* 自然继承。lyra logger propagate=False 不向 root 传播，无重复输出。
- uvicorn 原生 access log 格式不含耗时（'%s - "%s %s HTTP/%s" %d'），
  因此用 FastAPI middleware 补充耗时字段，替代原生 access log。
- middleware 在 uvicorn access log 之前执行（ASGI 栈：
  请求 → middleware → 路由 → 响应 → uvicorn access log），
  所以 middleware 记录的耗时覆盖了 uvicorn 原生 access log 的角色。
- 禁用 uvicorn 原生 access log（不设 handler + level 设为不可达），
  避免与 middleware 重复记录。
- 不引入第三方日志库（loguru/structlog），纯 stdlib logging。
- access logger 与 lyra 根 logger 共享 stdout/file handler，
  写同一个 lyra.log 文件（RotatingFileHandler 内部锁保证并发安全）。
"""

from __future__ import annotations

import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from backend.config import Settings

# 日志格式与日期格式（模块级常量，供测试引用）
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Access log 专用 logger 名称（与业务 logger 分离，便于独立控制级别）
ACCESS_LOGGER_NAME = "lyra.access"

# uvicorn.access 禁用级别（高于 CRITICAL，使任何 record 都被丢弃）
_ACCESS_DISABLED_LEVEL = logging.CRITICAL + 1

# 日志文件名
_LOG_FILENAME = "lyra.log"


def configure_logging(settings: Settings) -> None:
    """根据配置初始化日志系统。

    调用时机：main.py 模块加载时（在 app 创建之前），确保所有后续
    logger 调用都能正确输出。

    行为：
    - 始终创建 stdout handler（level 受 log_level 控制）
    - log_dir 非 None 时创建 RotatingFileHandler
    - log_dir 不存在时自动创建；创建/写入失败降级为仅 stdout
    - 接管 uvicorn error logger（统一格式）
    - 禁用 uvicorn 原生 access log（由 middleware 替代）
    - 配置 lyra.access logger（与 lyra 根共享 handler）
    - 配置 root logger（承接 backend.* 模块日志，见模块 docstring）
    - 启动后 log 一次配置摘要

    Args:
        settings: 应用配置实例。
    """
    log_level = settings.log_level_int()
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # ---- 配置 lyra 根 logger ----
    lyra_logger = logging.getLogger("lyra")
    lyra_logger.setLevel(log_level)
    # 清除旧 handler（防 basicConfig 残留或重复调用）
    lyra_logger.handlers.clear()
    lyra_logger.propagate = False  # lyra 自己输出，不向 root 传播（防重复）

    # stdout handler —— 始终存在
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(log_level)
    stdout_handler.setFormatter(formatter)
    lyra_logger.addHandler(stdout_handler)

    # 文件 handler —— 可选
    file_handler_added = False
    if settings.log_dir is not None:
        file_handler_added = _try_add_file_handler(lyra_logger, settings, formatter)

    # ---- 配置 uvicorn logger ----
    _configure_uvicorn_loggers(formatter, log_level)

    # ---- 配置 access log logger ----
    _configure_access_logger(formatter, log_level, settings, file_handler_added)

    # ---- 配置 root logger（承接 backend.* 等非 lyra 命名空间模块）----
    # backend.* 用 logging.getLogger(__name__)，不是 lyra 子 logger，
    # 靠 root 继承输出。不配 root 则 DEBUG/INFO 对业务模块失效。
    _configure_root_logger(formatter, log_level, settings, file_handler_added)

    # ---- 配置摘要 ----
    lyra_logger.info(
        "Logging configured: level=%s, log_dir=%s, file_handler=%s, access_log=enabled",
        settings.log_level,
        settings.log_dir if settings.log_dir is not None else "(stdout only)",
        file_handler_added,
    )


def _try_add_file_handler(
    lyra_logger: logging.Logger,
    settings: Settings,
    formatter: logging.Formatter,
) -> bool:
    """尝试添加 RotatingFileHandler，失败时降级。

    Returns:
        True 表示文件 handler 添加成功，False 表示降级。
    """
    log_dir = Path(settings.log_dir)  # type: ignore[arg-type]

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            filename=log_dir / _LOG_FILENAME,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(settings.log_level_int())
        file_handler.setFormatter(formatter)
        lyra_logger.addHandler(file_handler)
        return True
    except (OSError, PermissionError) as exc:
        lyra_logger.warning(
            "Failed to create log directory or file at '%s': %s. "
            "Falling back to stdout only.",
            settings.log_dir,
            exc,
        )
        return False


def _configure_uvicorn_loggers(formatter: logging.Formatter, log_level: int) -> None:
    """配置 uvicorn 的 error logger，使其使用我们的格式和 handler。

    uvicorn.access logger 禁用（由 middleware 替代原生 access log）。
    """
    # uvicorn.error —— 保留（启动/关闭/错误信息）
    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.handlers.clear()
    uvicorn_error.propagate = False
    uvicorn_error.setLevel(log_level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(formatter)
    uvicorn_error.addHandler(handler)

    # uvicorn.access —— 禁用原生 access log
    # 原因：原生格式不含耗时，且会与我们的 middleware 重复记录
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.handlers.clear()
    uvicorn_access.propagate = False
    uvicorn_access.setLevel(_ACCESS_DISABLED_LEVEL)  # 禁止任何输出


def _configure_root_logger(
    formatter: logging.Formatter,
    log_level: int,
    settings: Settings,
    file_handler_added: bool,
) -> None:
    """配置 root logger，承接 backend.* 等非 lyra 命名空间模块。

    backend.* 模块用 logging.getLogger(__name__)，命名空间是 backend.xxx，
    不是 lyra 的子 logger，会传播到 root。若 root 未配置（默认 WARNING、无
    handler、靠 lastResort），LYRA_LOG_LEVEL=DEBUG 对业务模块失效。

    此处给 root 设 level + stdout/file handler，使 backend.* 自然继承配置。
    lyra/lyra.access/uvicorn.* 均 propagate=False，不向 root 传播，无重复输出。
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(log_level)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(log_level)
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)

    if file_handler_added and settings.log_dir is not None:
        log_dir = Path(settings.log_dir)
        try:
            file_handler = RotatingFileHandler(
                filename=log_dir / _LOG_FILENAME,
                maxBytes=settings.log_max_bytes,
                backupCount=settings.log_backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(settings.log_level_int())
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except (OSError, PermissionError):
            # 文件 handler 创建失败已由 _try_add_file_handler 报过 warning，
            # 此处静默跳过
            pass


def _configure_access_logger(
    formatter: logging.Formatter,
    log_level: int,
    settings: Settings,
    file_handler_added: bool,
) -> None:
    """配置 lyra.access logger（middleware 写入此 logger）。

    与 lyra 根 logger 共享 stdout handler；若 file handler 可用则共享文件落盘。
    """
    access_logger = logging.getLogger(ACCESS_LOGGER_NAME)
    access_logger.handlers.clear()
    access_logger.propagate = False
    access_logger.setLevel(log_level)

    # stdout handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(log_level)
    stdout_handler.setFormatter(formatter)
    access_logger.addHandler(stdout_handler)

    # 文件 handler（与 lyra 根 logger 共享同一文件）
    if file_handler_added and settings.log_dir is not None:
        log_dir = Path(settings.log_dir)
        try:
            file_handler = RotatingFileHandler(
                filename=log_dir / _LOG_FILENAME,
                maxBytes=settings.log_max_bytes,
                backupCount=settings.log_backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(settings.log_level_int())
            file_handler.setFormatter(formatter)
            access_logger.addHandler(file_handler)
        except (OSError, PermissionError):
            # 文件 handler 创建失败已由 _try_add_file_handler 报过 warning，
            # 此处静默跳过
            pass


class AccessLogMiddleware(BaseHTTPMiddleware):
    """请求级 access log 中间件。

    记录格式：GET /api/play/1 200 12ms

    为什么不用 uvicorn 原生 access log：
    - uvicorn 原生格式 '%s - "%s %s HTTP/%s" %d' 不含耗时
    - 原生 access log 记录 query string（隐私考量：不记录）
    - 用 middleware 统一格式，可控性更强

    为什么不用 uvicorn --access-log：
    - 启动参数与代码内配置耦合，不如 middleware 灵活
    - 原生不支持自定义格式

    自用单用户场景，全量记录不做采样。

    注意：不记录 query string（隐私考量——query 可能含 token/敏感参数）。
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._logger = logging.getLogger(ACCESS_LOGGER_NAME)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start_time = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - start_time) * 1000

        # 只记录 HTTP 请求（排除 lifespan/starlette 内部事件）
        if request.method and request.url.path:
            self._logger.info(
                "%s %s %d %.0fms",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )

        return response
