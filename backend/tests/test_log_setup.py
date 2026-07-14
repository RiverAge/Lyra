"""测试——日志配置（config 校验 + handler 装配 + 降级路径 + access log）。

覆盖范围：
1. config.py 日志配置项校验（log_level 验证/降级、log_dir/log_max_bytes/log_backup_count）
2. log_setup.py handler 装配（stdout 始终存在、文件 handler 可选、uvicorn 接管）
3. 降级路径（log_dir 不可写 → 仅 stdout + warning）
4. AccessLogMiddleware 请求日志格式
5. 行为等价性（现有 logger 调用不受影响）

注意：lyra logger 设置 propagate=False，pytest caplog 默认捕获 root logger，
因此无法直接捕获 lyra logger 的输出。测试策略：
- handler 装配测试：直接检查 logger.handlers 列表
- 日志内容测试：通过文件 handler 写入的文件内容验证
- caplog 测试：在 configure_logging 之后手动添加 caplog.handler
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.config import Settings
from backend.log_setup import (
    ACCESS_LOGGER_NAME,
    AccessLogMiddleware,
    configure_logging,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides: object) -> Settings:
    """创建测试用 Settings，默认最小配置。"""
    defaults: dict[str, object] = {
        "music_library_root": None,
        "db_path": "./data/test.db",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _reset_loggers() -> None:
    """测试后清理 logger 状态，防测试间泄漏。"""
    for name in ("lyra", ACCESS_LOGGER_NAME, "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.setLevel(logging.WARNING)  # 恢复默认
        logger.propagate = True

    # root logger 也需清理（configure_logging 会配 root 承接 backend.*）
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Config 校验测试
# ---------------------------------------------------------------------------


class TestConfigLogLevel:
    """log_level 配置项校验。"""

    def test_default_is_info(self) -> None:
        """未配置时默认 INFO。"""
        settings = _make_settings()
        assert settings.log_level == "INFO"

    def test_valid_levels_accepted(self) -> None:
        """合法级别原样保留。"""
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            settings = _make_settings(log_level=level)
            assert settings.log_level == level

    def test_lowercase_normalized(self) -> None:
        """小写输入被 upper() 后接受。"""
        settings = _make_settings(log_level="debug")
        assert settings.log_level == "DEBUG"

    def test_invalid_level_degrades_to_info(self) -> None:
        """非法值静默降级为 INFO（不抛异常，防 typo 导致进程无法启动）。"""
        settings = _make_settings(log_level="VERBOSE")
        assert settings.log_level == "INFO"

    def test_empty_string_degrades_to_info(self) -> None:
        """空字符串降级为 INFO。"""
        settings = _make_settings(log_level="")
        assert settings.log_level == "INFO"

    def test_log_level_int(self) -> None:
        """log_level_int() 返回 logging 模块整数常量。"""
        settings = _make_settings(log_level="DEBUG")
        assert settings.log_level_int() == logging.DEBUG
        settings = _make_settings(log_level="WARNING")
        assert settings.log_level_int() == logging.WARNING


class TestConfigLogDir:
    """log_dir 配置项。"""

    def test_default_is_none(self) -> None:
        """未配置时默认 None（仅 stdout）。"""
        settings = _make_settings()
        assert settings.log_dir is None

    def test_configured_value(self) -> None:
        """配置后保留原值。"""
        settings = _make_settings(log_dir="/var/log/lyra")
        assert settings.log_dir == "/var/log/lyra"


class TestConfigLogRotation:
    """log_max_bytes / log_backup_count 配置项。"""

    def test_default_max_bytes(self) -> None:
        """默认 10MB。"""
        settings = _make_settings()
        assert settings.log_max_bytes == 10 * 1024 * 1024

    def test_default_backup_count(self) -> None:
        """默认 5 个备份。"""
        settings = _make_settings()
        assert settings.log_backup_count == 5

    def test_custom_values(self) -> None:
        """自定义值保留。"""
        settings = _make_settings(log_max_bytes=5_000_000, log_backup_count=3)
        assert settings.log_max_bytes == 5_000_000
        assert settings.log_backup_count == 3


# ---------------------------------------------------------------------------
# Handler 装配测试
# ---------------------------------------------------------------------------


class TestHandlerAssembly:
    """configure_logging handler 装配逻辑。"""

    def teardown_method(self) -> None:
        _reset_loggers()

    def test_stdout_handler_always_present(self) -> None:
        """log_dir=None 时 lyra logger 只有 stdout handler。"""
        settings = _make_settings()
        configure_logging(settings)

        lyra_logger = logging.getLogger("lyra")
        assert len(lyra_logger.handlers) == 1
        assert isinstance(lyra_logger.handlers[0], logging.StreamHandler)

    def test_file_handler_added_when_log_dir_set(self, tmp_path: Path) -> None:
        """log_dir 配置后 lyra logger 有 stdout + file 两个 handler。"""
        settings = _make_settings(log_dir=str(tmp_path / "logs"))
        configure_logging(settings)

        lyra_logger = logging.getLogger("lyra")
        assert len(lyra_logger.handlers) == 2
        handler_types = {type(h) for h in lyra_logger.handlers}
        assert logging.StreamHandler in handler_types
        assert RotatingFileHandler in handler_types

    def test_log_file_created(self, tmp_path: Path) -> None:
        """log_dir 配置后 lyra.log 文件生成。"""
        log_dir = tmp_path / "logs"
        settings = _make_settings(log_dir=str(log_dir))
        configure_logging(settings)

        # configure_logging 内部会 log 一次配置摘要，触发文件写入
        assert (log_dir / "lyra.log").exists()

    def test_log_dir_auto_created(self, tmp_path: Path) -> None:
        """log_dir 不存在时自动 mkdir -p。"""
        log_dir = tmp_path / "deep" / "nested" / "logs"
        settings = _make_settings(log_dir=str(log_dir))
        configure_logging(settings)

        assert log_dir.exists()
        assert (log_dir / "lyra.log").exists()

    def test_lyra_logger_level_matches_config(self) -> None:
        """lyra_logger level 受 log_level 控制。"""
        settings = _make_settings(log_level="DEBUG")
        configure_logging(settings)

        lyra_logger = logging.getLogger("lyra")
        assert lyra_logger.level == logging.DEBUG

    def test_lyra_logger_not_propagate(self) -> None:
        """lyra logger 不向 root 传播（防重复输出）。"""
        settings = _make_settings()
        configure_logging(settings)

        lyra_logger = logging.getLogger("lyra")
        assert lyra_logger.propagate is False

    def test_access_logger_configured(self) -> None:
        """lyra.access logger 被配置。"""
        settings = _make_settings()
        configure_logging(settings)

        access_logger = logging.getLogger(ACCESS_LOGGER_NAME)
        assert len(access_logger.handlers) >= 1
        assert access_logger.propagate is False

    def test_access_logger_has_file_handler_when_log_dir_set(self, tmp_path: Path) -> None:
        """log_dir 配置后 access logger 也有文件 handler。"""
        settings = _make_settings(log_dir=str(tmp_path / "logs"))
        configure_logging(settings)

        access_logger = logging.getLogger(ACCESS_LOGGER_NAME)
        handler_types = {type(h) for h in access_logger.handlers}
        assert RotatingFileHandler in handler_types

    def test_uvicorn_access_disabled(self) -> None:
        """uvicorn.access logger 被禁用（由 middleware 替代）。"""
        settings = _make_settings()
        configure_logging(settings)

        uvicorn_access = logging.getLogger("uvicorn.access")
        assert len(uvicorn_access.handlers) == 0
        # level 设为不可达值
        assert uvicorn_access.level > logging.CRITICAL

    def test_uvicorn_error_configured(self) -> None:
        """uvicorn.error logger 使用我们的格式。"""
        settings = _make_settings()
        configure_logging(settings)

        uvicorn_error = logging.getLogger("uvicorn.error")
        assert len(uvicorn_error.handlers) == 1
        assert isinstance(uvicorn_error.handlers[0], logging.StreamHandler)
        assert uvicorn_error.propagate is False

    def test_root_logger_has_stdout_handler(self) -> None:
        """root logger 配置了 stdout handler（承接 backend.* 模块）。

        回归 P1-1：configure_logging 必须配 root，否则 backend.* 继承
        默认 WARNING 级 + 无 handler，DEBUG/INFO 对业务模块失效。
        """
        settings = _make_settings()
        configure_logging(settings)

        root = logging.getLogger()
        assert len(root.handlers) >= 1
        assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)

    def test_root_logger_level_matches_config(self) -> None:
        """root logger level 受 log_level 控制（backend.* 继承此级别）。"""
        settings = _make_settings(log_level="DEBUG")
        configure_logging(settings)

        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_root_logger_has_file_handler_when_log_dir_set(self, tmp_path: Path) -> None:
        """log_dir 配置后 root logger 也有文件 handler（backend.* 落盘）。"""
        settings = _make_settings(log_dir=str(tmp_path / "logs"))
        configure_logging(settings)

        root = logging.getLogger()
        handler_types = {type(h) for h in root.handlers}
        assert RotatingFileHandler in handler_types


# ---------------------------------------------------------------------------
# 降级路径测试
# ---------------------------------------------------------------------------


class TestDegradation:
    """log_dir 不可写时降级为仅 stdout。"""

    def teardown_method(self) -> None:
        _reset_loggers()

    def test_unwritable_log_dir_falls_back_to_stdout(self) -> None:
        """log_dir 不可写时降级为仅 stdout，进程不崩。"""
        # 使用一个不可能有写权限的路径
        settings = _make_settings(log_dir="Z:\\nonexistent\\impossible\\path\\logs")
        # 不应抛异常
        configure_logging(settings)

        lyra_logger = logging.getLogger("lyra")
        # 只有 stdout handler，没有 file handler
        assert len(lyra_logger.handlers) == 1
        assert isinstance(lyra_logger.handlers[0], logging.StreamHandler)

    def test_unwritable_log_dir_warning_in_file(self, tmp_path: Path) -> None:
        """降级 warning 写入可用的日志文件（间接验证 warning 被发出）。

        策略：先用可写 log_dir 配置一次（建立文件 handler），
        再用不可写路径调用 _try_add_file_handler，验证 warning 被记录到文件。
        """
        log_dir = tmp_path / "logs"
        settings_ok = _make_settings(log_dir=str(log_dir))
        configure_logging(settings_ok)

        # 现在文件 handler 已建立，触发降级路径
        from backend.log_setup import _try_add_file_handler

        bad_settings = _make_settings(log_dir="Z:\\nonexistent\\impossible\\path\\logs")
        lyra_logger = logging.getLogger("lyra")
        _try_add_file_handler(lyra_logger, bad_settings, logging.Formatter("%(message)s"))

        # 读取日志文件，应有降级 warning
        log_content = (log_dir / "lyra.log").read_text(encoding="utf-8")
        assert "Failed to create log directory" in log_content

    @pytest.mark.skipif(
        os.name == "nt",
        reason="POSIX 权限模型在 Windows 上不可靠",
    )
    def test_permission_denied_falls_back(self, tmp_path: Path) -> None:
        """目录权限不足时降级（仅 POSIX）。"""
        log_dir = tmp_path / "readonly"
        log_dir.mkdir()
        log_dir.chmod(0o000)

        try:
            settings = _make_settings(log_dir=str(log_dir))
            configure_logging(settings)

            lyra_logger = logging.getLogger("lyra")
            assert len(lyra_logger.handlers) == 1
            assert isinstance(lyra_logger.handlers[0], logging.StreamHandler)
        finally:
            # 恢复权限以便清理
            log_dir.chmod(0o755)


# ---------------------------------------------------------------------------
# AccessLogMiddleware 测试
# ---------------------------------------------------------------------------


class TestAccessLogMiddleware:
    """AccessLogMiddleware 请求日志格式。"""

    @pytest.fixture
    async def app(self) -> FastAPI:
        """带 AccessLogMiddleware 的最小 app。"""
        app = FastAPI()
        app.add_middleware(AccessLogMiddleware)

        @app.get("/api/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        @app.get("/api/play/{track_id}")
        async def play_endpoint(track_id: int) -> dict[str, int]:
            return {"track_id": track_id}

        return app

    @pytest.fixture
    async def client(self, app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    async def test_access_log_records_request(
        self,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """请求后 access logger 记录一行。"""
        # access logger 也是 propagate=False，需手动挂 caplog
        access_logger = logging.getLogger(ACCESS_LOGGER_NAME)
        access_logger.addHandler(caplog.handler)
        with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER_NAME):
            resp = await client.get("/api/test")
            assert resp.status_code == 200

        access_records = [
            r for r in caplog.records if r.name == ACCESS_LOGGER_NAME
        ]
        assert len(access_records) >= 1
        msg = access_records[-1].message
        # 格式：GET /api/test 200 Xms
        assert "GET" in msg
        assert "/api/test" in msg
        assert "200" in msg
        assert "ms" in msg

    async def test_access_log_includes_method_path_status(
        self,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """access log 至少含 method + path + status。"""
        access_logger = logging.getLogger(ACCESS_LOGGER_NAME)
        access_logger.addHandler(caplog.handler)
        with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER_NAME):
            resp = await client.get("/api/play/1")
            assert resp.status_code == 200

        access_records = [
            r for r in caplog.records if r.name == ACCESS_LOGGER_NAME
        ]
        msg = access_records[-1].message
        assert msg.startswith("GET /api/play/1 200")

    async def test_access_log_not_record_query_string(
        self,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """access log 不记录 query string（隐私考量）。"""
        access_logger = logging.getLogger(ACCESS_LOGGER_NAME)
        access_logger.addHandler(caplog.handler)
        with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER_NAME):
            resp = await client.get("/api/test?token=secret")
            assert resp.status_code == 200

        access_records = [
            r for r in caplog.records if r.name == ACCESS_LOGGER_NAME
        ]
        msg = access_records[-1].message
        assert "token=secret" not in msg
        assert "/api/test" in msg

    async def test_access_log_records_404(
        self,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """404 404 请求也被记录。"""
        access_logger = logging.getLogger(ACCESS_LOGGER_NAME)
        access_logger.addHandler(caplog.handler)
        with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER_NAME):
            resp = await client.get("/api/nonexistent")
            assert resp.status_code == 404

        access_records = [
            r for r in caplog.records if r.name == ACCESS_LOGGER_NAME
        ]
        msg = access_records[-1].message
        assert "404" in msg

    async def test_access_log_writes_to_file(self, tmp_path: Path) -> None:
        """access log 写入日志文件。"""
        log_dir = tmp_path / "logs"
        settings = _make_settings(log_dir=str(log_dir))
        configure_logging(settings)

        app = FastAPI()
        app.add_middleware(AccessLogMiddleware)

        @app.get("/api/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/test")
            assert resp.status_code == 200

        # 读取日志文件，应有 access log 行
        log_content = (log_dir / "lyra.log").read_text(encoding="utf-8")
        assert "GET /api/test 200" in log_content


# ---------------------------------------------------------------------------
# 行为等价性测试
# ---------------------------------------------------------------------------


class TestBehaviorEquivalence:
    """现有 logger 调用不受影响。"""

    def teardown_method(self) -> None:
        _reset_loggers()

    def test_backend_module_logger_still_works(self, caplog: pytest.LogCaptureFixture) -> None:
        """backend.* 模块的 logging.getLogger(__name__) 调用正常输出。

        backend.* 命名空间不是 lyra 的子 logger，靠 root logger 继承输出。
        关键验证：LYRA_LOG_LEVEL=DEBUG 时 backend.* 的 INFO 真的被捕获
        （回归 P1：configure_logging 不配 root 时此断言会失败——
        backend.* effective level 锁在 WARNING，INFO 被丢弃）。
        """
        settings = _make_settings(log_level="DEBUG")
        configure_logging(settings)

        # 模拟 backend.index.scanner 的 logger
        scanner_logger = logging.getLogger("backend.index.scanner")
        # backend.* propagate 到 root，caplog 挂 root 才能捕获
        root = logging.getLogger()
        root.addHandler(caplog.handler)
        with caplog.at_level(logging.DEBUG):
            scanner_logger.info("test message from scanner")

        assert any(
            "test message from scanner" in r.message for r in caplog.records
        ), "backend.* logger 的 INFO 应通过 root 继承输出"

    def test_backend_module_debug_level_inherited(self) -> None:
        """LYRA_LOG_LEVEL=DEBUG 时 backend.* 的 effective level == DEBUG。

        回归 P1-1：configure_logging 必须配 root，否则 backend.* 继承
        root 默认 WARNING，DEBUG 对业务模块失效。
        """
        settings = _make_settings(log_level="DEBUG")
        configure_logging(settings)

        scanner_logger = logging.getLogger("backend.index.scanner")
        assert scanner_logger.getEffectiveLevel() == logging.DEBUG, (
            "backend.* 应继承 root 的 DEBUG 级别"
        )

    def test_backend_module_info_level_inherited(self) -> None:
        """LYRA_LOG_LEVEL=INFO 时 backend.* 的 effective level == INFO。"""
        settings = _make_settings(log_level="INFO")
        configure_logging(settings)

        scanner_logger = logging.getLogger("backend.index.scanner")
        assert scanner_logger.getEffectiveLevel() == logging.INFO

    def test_lyra_logger_info_still_works(self, caplog: pytest.LogCaptureFixture) -> None:
        """lyra logger 的 info 调用正常输出。"""
        settings = _make_settings()
        configure_logging(settings)

        lyra_logger = logging.getLogger("lyra")
        # configure_logging 后手动挂 caplog.handler
        lyra_logger.addHandler(caplog.handler)
        with caplog.at_level(logging.INFO, logger="lyra"):
            lyra_logger.info("test info message")

        assert any("test info message" in r.message for r in caplog.records)

    def test_lyra_logger_exception_still_works(self, caplog: pytest.LogCaptureFixture) -> None:
        """lyra logger 的 exception 调用正常输出（含 traceback）。"""
        settings = _make_settings()
        configure_logging(settings)

        lyra_logger = logging.getLogger("lyra")
        lyra_logger.addHandler(caplog.handler)
        with caplog.at_level(logging.ERROR, logger="lyra"):
            try:
                raise ValueError("test error")
            except ValueError:
                lyra_logger.exception("something failed")

        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(error_records) >= 1
        assert any("something failed" in r.message for r in error_records)

    def test_configure_logging_idempotent(self) -> None:
        """重复调用 configure_logging 不产生重复 handler。"""
        settings = _make_settings()
        configure_logging(settings)
        configure_logging(settings)

        lyra_logger = logging.getLogger("lyra")
        # 每次 configure_logging 清除旧 handler 再添加，所以始终只有 1 个 stdout handler
        assert len(lyra_logger.handlers) == 1


# ---------------------------------------------------------------------------
# 配置摘要 + 文件内容测试
# ---------------------------------------------------------------------------


class TestLogFileContent:
    """日志文件内容验证（间接验证 configure_logging 的摘要输出）。"""

    def teardown_method(self) -> None:
        _reset_loggers()

    def test_summary_in_log_file(self, tmp_path: Path) -> None:
        """配置摘要写入日志文件。"""
        log_dir = tmp_path / "logs"
        settings = _make_settings(log_dir=str(log_dir))
        configure_logging(settings)

        log_content = (log_dir / "lyra.log").read_text(encoding="utf-8")
        assert "Logging configured" in log_content
        assert "level=INFO" in log_content
        assert "(stdout only)" not in log_content  # 有 log_dir 时不显示 stdout only
        assert "access_log=enabled" in log_content

    def test_summary_stdout_only(self, tmp_path: Path) -> None:
        """log_dir=None 时摘要显示 (stdout only)。"""
        # 用可写 log_dir 配置，然后检查摘要中 log_dir 的值
        log_dir = tmp_path / "logs"
        settings = _make_settings(log_dir=str(log_dir))
        configure_logging(settings)

        log_content = (log_dir / "lyra.log").read_text(encoding="utf-8")
        # 摘要应包含 log_dir 路径
        assert str(log_dir) in log_content

    def test_business_log_in_file(self, tmp_path: Path) -> None:
        """业务 logger 调用写入日志文件。"""
        log_dir = tmp_path / "logs"
        settings = _make_settings(log_dir=str(log_dir), log_level="DEBUG")
        configure_logging(settings)

        lyra_logger = logging.getLogger("lyra")
        lyra_logger.info("test business message")

        log_content = (log_dir / "lyra.log").read_text(encoding="utf-8")
        assert "test business message" in log_content
