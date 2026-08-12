"""Logging setup shared by the API process and the Celery workers.

Every log line carries a correlation id so a request can be followed from the
HTTP handler into the task that finishes the work asynchronously. The id is
held in a :class:`~contextvars.ContextVar`, which propagates correctly across
``async``/threadpool boundaries, and is injected by a handler-level filter so
third-party records (uvicorn, sqlalchemy, celery) get it too.
"""

import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from baymax.config import get_config

#: Correlation id for the work currently in flight ("-" when outside a request
#: or task). Set by the API middleware and by each Celery task.
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")

_configured = False


class CorrelationIdFilter(logging.Filter):
    """Stamps every record with the current correlation id."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id.get()
        return True


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def bind_correlation_id(value: str | None = None) -> Iterator[str]:
    """Bind a correlation id for the duration of the block."""
    value = value or new_correlation_id()
    token = correlation_id.set(value)
    try:
        yield value
    finally:
        correlation_id.reset(token)


def configure_logging(*, force: bool = False) -> None:
    """Install the root handler. Idempotent — safe to call from every entrypoint."""
    global _configured
    if _configured and not force:
        return

    config = get_config().logging

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt=config.format, datefmt=config.date_format))
    handler.addFilter(CorrelationIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(config.level)

    # Quiet down chatty third-party loggers without losing our own DEBUG output.
    for name, level in config.library_levels.items():
        logging.getLogger(name).setLevel(level)

    # uvicorn and gunicorn install their own handlers with propagate=False, so
    # their lines would bypass our formatter and print without a correlation
    # id. create_app() runs after they set that up, so clearing wins.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "gunicorn", "gunicorn.error"):
        server_logger = logging.getLogger(name)
        server_logger.handlers.clear()
        server_logger.propagate = True

    _configured = True
    logging.getLogger(__name__).debug("logging configured at %s", config.level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def log_duration(
    logger: logging.Logger,
    operation: str,
    *,
    level: int = logging.INFO,
    **context: object,
) -> Iterator[None]:
    """Log the start, duration and outcome of an operation.

    Failures are logged with the elapsed time before the exception propagates,
    which is what makes a slow-then-failing embedding call diagnosable.
    """
    suffix = " ".join(f"{key}={value}" for key, value in context.items())
    detail = f"{operation} {suffix}".strip()
    logger.log(level, "start: %s", detail)

    started = time.perf_counter()
    try:
        yield
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        logger.exception("failed: %s elapsed_ms=%.1f error=%s", detail, elapsed, type(exc).__name__)
        raise
    else:
        elapsed = (time.perf_counter() - started) * 1000
        logger.log(level, "done: %s elapsed_ms=%.1f", detail, elapsed)
