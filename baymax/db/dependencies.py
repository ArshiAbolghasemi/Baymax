"""FastAPI dependencies for database access.

Lives here rather than in ``baymax.api`` so a domain router can depend on it
without importing the application package — that import direction is what made
the Celery worker fail to load its task module.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from baymax.common.logging import get_logger
from baymax.db.session import get_session_factory

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


SessionDep = Annotated[Session, Depends(get_session)]
