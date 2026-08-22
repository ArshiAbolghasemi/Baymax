"""Loguru-based application logging with request/task correlation.

Application modules use :func:`get_logger`. Standard-library records emitted by
Uvicorn, Celery, SQLAlchemy, OpenAI, and other dependencies are intercepted and
forwarded to the same Loguru sink, so one correlation id and format cover the
whole process.
"""

import logging
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from loguru import logger as _loguru_logger

from hiro.config import get_config

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")

_configured = False


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


def _patch_record(record: dict[str, Any]) -> None:
    record["extra"]["correlation_id"] = correlation_id.get()
    record["extra"].setdefault("component", record["name"])


class InterceptHandler(logging.Handler):
    """Forward standard-library records into Loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        _loguru_logger.bind(component=record.name).opt(
            depth=depth,
            exception=record.exc_info,
        ).log(level, record.getMessage())


class AppLogger:
    """Small compatibility façade backed entirely by Loguru.

    It accepts the repository's existing ``logging``-style ``%s`` arguments,
    allowing the backend migration without losing call-site information.
    New code can bind structured context with :meth:`bind`.
    """

    def __init__(self, bound_logger: Any) -> None:
        self._logger = bound_logger

    @staticmethod
    def _message(message: object, args: tuple[object, ...]) -> str:
        text = str(message)
        if not args:
            return text
        try:
            return text % args
        except TypeError, ValueError:
            return " ".join((text, *(str(arg) for arg in args)))

    def bind(self, **context: object) -> AppLogger:
        return AppLogger(self._logger.bind(**context))

    def log(
        self,
        level: str | int,
        message: object,
        *args: object,
        exc_info: object = False,
    ) -> None:
        if isinstance(level, int):
            level = logging.getLevelName(level)
        self._logger.opt(exception=exc_info).log(level, self._message(message, args))

    def debug(self, message: object, *args: object, exc_info: object = False) -> None:
        self.log("DEBUG", message, *args, exc_info=exc_info)

    def info(self, message: object, *args: object, exc_info: object = False) -> None:
        self.log("INFO", message, *args, exc_info=exc_info)

    def warning(self, message: object, *args: object, exc_info: object = False) -> None:
        self.log("WARNING", message, *args, exc_info=exc_info)

    def error(self, message: object, *args: object, exc_info: object = False) -> None:
        self.log("ERROR", message, *args, exc_info=exc_info)

    def exception(self, message: object, *args: object) -> None:
        self.log("ERROR", message, *args, exc_info=True)


def configure_logging(*, force: bool = False) -> None:
    """Configure Loguru and intercept standard-library logging once per process."""
    global _configured
    if _configured and not force:
        return

    config = get_config().logging
    _loguru_logger.remove()
    _loguru_logger.configure(
        extra={"correlation_id": "-", "component": "-"},
        patcher=_patch_record,
    )
    _loguru_logger.add(
        sys.stderr,
        level=config.level,
        format=config.format,
        backtrace=False,
        diagnose=False,
        enqueue=False,
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(InterceptHandler())
    root.setLevel(config.level)

    for name, level in config.library_levels.items():
        logging.getLogger(name).setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "gunicorn", "gunicorn.error"):
        external_logger = logging.getLogger(name)
        external_logger.handlers.clear()
        external_logger.propagate = True

    _configured = True
    get_logger(__name__).debug("logging configured backend=loguru level=%s", config.level)


def get_logger(name: str) -> AppLogger:
    return AppLogger(_loguru_logger.bind(component=name))


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
