"""Declarative base shared by every domain's models.

Domain packages subclass this so a single ``Base.metadata`` describes the whole
schema, which is what lets Alembic autogenerate see every table.
"""

import uuid

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for every Baymax table."""


def uid_pk() -> Mapped[uuid.UUID]:
    """The project-wide primary key: a client-generated UUID named ``uid``."""
    return mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def uid_fk_type() -> PG_UUID:
    return PG_UUID(as_uuid=True)
