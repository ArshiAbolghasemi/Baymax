"""Engine and session plumbing, shared by the API and the Celery worker.

The engine is created lazily so importing the package never opens a socket —
that matters for the worker, which forks after import.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from baymax.common.logging import get_logger
from baymax.config import get_config

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    config = get_config().database
    logger.debug(
        "creating engine pool_size=%s max_overflow=%s",
        config.pool_size,
        config.max_overflow,
    )
    return create_engine(
        config.url,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_pre_ping=config.pool_pre_ping,
        echo=config.echo,
        future=True,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def dispose_engine() -> None:
    """Drop pooled connections — call after forking a worker process."""
    if get_engine.cache_info().currsize:
        logger.debug("disposing engine connection pool")
        get_engine().dispose()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on any exception."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        logger.warning("rolling back transaction", exc_info=True)
        session.rollback()
        raise
    finally:
        session.close()
