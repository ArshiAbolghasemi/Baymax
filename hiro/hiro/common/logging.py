"""OpenTelemetry logging with request/task correlation and structured context."""

import logging
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from hiro.config import get_config

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")

_configured = False
_provider: LoggerProvider | None = None


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def bind_correlation_id(value: str | None = None) -> Iterator[str]:
    """Bind a correlation id for all logs in the current async/thread context."""
    value = value or new_correlation_id()
    token = correlation_id.set(value)
    try:
        yield value
    finally:
        correlation_id.reset(token)


class ContextFilter(logging.Filter):
    """Attach shared context before console and OTLP handlers read a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id.get()
        if not hasattr(record, "component"):
            record.component = record.name
        return True


class AppLogger:
    """Logging façade that adds bindable structured attributes."""

    def __init__(self, logger: logging.Logger, context: dict[str, object] | None = None) -> None:
        self._logger = logger
        self._context = context or {}

    def bind(self, **context: object) -> AppLogger:
        return AppLogger(self._logger, self._context | context)

    def log(
        self,
        level: str | int,
        message: object,
        *args: object,
        exc_info: object = False,
    ) -> None:
        if isinstance(level, str):
            level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        self._logger.log(
            level,
            message,
            *args,
            exc_info=exc_info,
            extra={"component": self._logger.name} | self._context,
            stacklevel=2,
        )

    def debug(self, message: object, *args: object, exc_info: object = False) -> None:
        self.log(logging.DEBUG, message, *args, exc_info=exc_info)

    def info(self, message: object, *args: object, exc_info: object = False) -> None:
        self.log(logging.INFO, message, *args, exc_info=exc_info)

    def warning(self, message: object, *args: object, exc_info: object = False) -> None:
        self.log(logging.WARNING, message, *args, exc_info=exc_info)

    def error(self, message: object, *args: object, exc_info: object = False) -> None:
        self.log(logging.ERROR, message, *args, exc_info=exc_info)

    def exception(self, message: object, *args: object) -> None:
        self.log(logging.ERROR, message, *args, exc_info=True)


def configure_logging(*, force: bool = False) -> None:
    """Configure console logging and batched OTLP/HTTP export once per process."""
    global _configured, _provider
    if _configured and not force:
        return
    if _provider is not None:
        _provider.shutdown()

    config = get_config().logging
    context_filter = ContextFilter()

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(config.format))
    console.addFilter(context_filter)

    _provider = LoggerProvider(
        resource=Resource.create(
            {
                "service.name": config.service_name,
                "service.version": config.service_version,
            }
        )
    )
    _provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))

    otlp = LoggingHandler(level=config.level, logger_provider=_provider)
    otlp.addFilter(context_filter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(otlp)
    root.setLevel(config.level)

    for name, level in config.library_levels.items():
        logging.getLogger(name).setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "gunicorn", "gunicorn.error"):
        external_logger = logging.getLogger(name)
        external_logger.handlers.clear()
        external_logger.propagate = True

    _configured = True
    get_logger(__name__).debug("logging configured backend=opentelemetry level=%s", config.level)


def shutdown_logging() -> None:
    """Flush pending OpenTelemetry logs and stop the exporter."""
    global _configured, _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None
    _configured = False


def get_logger(name: str) -> AppLogger:
    return AppLogger(logging.getLogger(name))


@contextmanager
def log_duration(
    logger: AppLogger,
    operation: str,
    *,
    level: int | str = logging.INFO,
    **context: object,
) -> Iterator[None]:
    """Log the beginning, latency, and outcome of an operation."""
    operation_logger = logger.bind(operation=operation, **context)
    detail = " ".join((operation, *(f"{key}={value}" for key, value in context.items())))
    operation_logger.log(level, "operation started %s", detail)
    started = time.perf_counter()
    try:
        yield
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1_000
        operation_logger.exception(
            "operation failed %s elapsed_ms=%.1f error_type=%s",
            detail,
            elapsed,
            type(exc).__name__,
        )
        raise
    else:
        elapsed = (time.perf_counter() - started) * 1_000
        operation_logger.log(level, "operation completed %s elapsed_ms=%.1f", detail, elapsed)
