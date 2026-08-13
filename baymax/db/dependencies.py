"""FastAPI dependencies for database access.

These live here rather than in ``baymax.api`` so a domain router can depend on
them without importing the application package — that import direction is what
made the Celery worker fail to load its task module.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from baymax.common.logging import get_logger
from baymax.db.session import async_session_scope, get_session_factory

logger = get_logger(__name__)


def get_session() -> Iterator[Session]:
    """Per-request session; commits on success, rolls back on failure."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        logger.warning("request failed, rolling back session", exc_info=True)
        session.rollback()
        raise
    finally:
        session.close()


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """Per-request async session, for the async handlers."""
    async with async_session_scope() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
AsyncSessionDep = Annotated[AsyncSession, Depends(get_async_session)]
