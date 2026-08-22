"""Engine and session plumbing for the whole application.

Two engines over one Postgres database: a sync one for the API's knowledge base
handlers and the Celery worker, and an async one for the chat handlers and the
streaming task. Both are driven by psycopg 3 from the same
``postgresql+psycopg://`` URL.

Engines are created lazily so importing the package never opens a socket — that
matters for the worker, which forks after import.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from hiro.common.logging import get_logger
from hiro.config import get_config

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Sync
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Async
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def get_async_engine() -> AsyncEngine:
    config = get_config().database
    logger.debug("creating async engine")
    return create_async_engine(
        config.url,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_pre_ping=config.pool_pre_ping,
        echo=config.echo,
        future=True,
    )


@lru_cache(maxsize=1)
def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=get_async_engine(), expire_on_commit=False, autoflush=False)


async def dispose_async_engine() -> None:
    """Close pooled connections — call on application shutdown."""
    if get_async_engine.cache_info().currsize:
        await get_async_engine().dispose()
        logger.debug("disposed async engine connection pool")


@asynccontextmanager
async def async_session_scope() -> AsyncIterator[AsyncSession]:
    """Async transactional scope: commit on success, roll back on any exception."""
    async with get_async_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            logger.warning("rolling back async transaction", exc_info=True)
            await session.rollback()
            raise
