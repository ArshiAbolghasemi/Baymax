"""Celery application shared by every domain.

Run a worker with::

    uv run celery -A hiro.worker.app:celery_app worker --loglevel=info

``from celery import Celery`` below resolves to the installed distribution, not
to this package — Python 3 imports are absolute.

Task modules are listed in ``include`` rather than autodiscovered so the set of
registered tasks is explicit and greppable.
"""

from typing import Any

from celery import Celery
from celery.signals import (
    setup_logging,
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    worker_process_init,
)

from hiro.common.logging import configure_logging, get_logger
from hiro.config import get_config
from hiro.db.session import dispose_engine

logger = get_logger(__name__)

TASK_MODULES = ["hiro.knowledge_base.tasks"]

_config = get_config().celery

celery_app = Celery(
    "baymax",
    broker=_config.broker_url,
    backend=_config.result_backend,
    include=TASK_MODULES,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Late ack + no prefetch: a task lost to a worker crash is redelivered
    # rather than silently dropped, which matters because indexing is the only
    # thing that gets a pair into Qdrant.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=_config.task_soft_time_limit,
    task_time_limit=_config.task_time_limit,
)


@setup_logging.connect
def _configure_worker_logging(**_: Any) -> None:
    """Use our logging config instead of letting Celery hijack the root logger."""
    configure_logging(force=True)


@worker_process_init.connect
def _reset_engine_after_fork(**_: Any) -> None:
    """Never share a pooled connection across a fork."""
    dispose_engine()


@task_prerun.connect
def _log_task_start(task_id: str | None = None, task: Any = None, **_: Any) -> None:
    logger.info("task started name=%s id=%s", getattr(task, "name", "?"), task_id)


@task_postrun.connect
def _log_task_end(
    task_id: str | None = None, task: Any = None, state: str | None = None, **_: Any
) -> None:
    logger.info("task finished name=%s id=%s state=%s", getattr(task, "name", "?"), task_id, state)


@task_retry.connect
def _log_task_retry(request: Any = None, reason: Any = None, **_: Any) -> None:
    logger.warning(
        "task retrying name=%s id=%s reason=%s",
        getattr(request, "task", "?"),
        getattr(request, "id", "?"),
        reason,
    )


@task_failure.connect
def _log_task_failure(
    task_id: str | None = None, exception: BaseException | None = None, **_: Any
) -> None:
    logger.error("task failed id=%s error=%r", task_id, exception)
