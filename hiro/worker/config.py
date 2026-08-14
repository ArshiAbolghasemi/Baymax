"""Celery configuration."""

from dynaconf import Dynaconf, Validator

from common.env import dynaconf_kwargs


class CeleryConfig(Dynaconf):
    """Broker, result backend and task retry policy."""

    def __init__(self) -> None:
        super().__init__(
            **dynaconf_kwargs([Validator("CELERY_BROKER_URL", must_exist=True, is_type_of=str)])
        )

    @property
    def broker_url(self) -> str:
        return str(self.get("CELERY_BROKER_URL"))

    @property
    def result_backend(self) -> str:
        """Defaults to the broker when unset — same Redis, different database."""
        return str(self.get("CELERY_RESULT_BACKEND", self.broker_url))

    @property
    def task_max_retries(self) -> int:
        return int(self.get("CELERY_TASK_MAX_RETRIES", 5))

    @property
    def task_retry_backoff(self) -> int:
        return int(self.get("CELERY_TASK_RETRY_BACKOFF", 5))

    @property
    def task_retry_backoff_max(self) -> int:
        return int(self.get("CELERY_TASK_RETRY_BACKOFF_MAX", 300))

    @property
    def task_soft_time_limit(self) -> int:
        return int(self.get("CELERY_TASK_SOFT_TIME_LIMIT", 540))

    @property
    def task_time_limit(self) -> int:
        return int(self.get("CELERY_TASK_TIME_LIMIT", 43200))
