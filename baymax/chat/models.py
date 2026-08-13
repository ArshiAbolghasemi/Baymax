"""ORM models for chat.

These share ``baymax.db.base.Base`` with the knowledge base: chat lives in the
same Postgres database, so one metadata describes the whole schema and Alembic
manages both.
"""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from baymax.db.base import Base, uid_fk_type

Role = Literal["user", "ai"]


class Session(Base):
    """One conversation, owned by a user."""

    __tablename__ = "session"

    session_uid: Mapped[uuid.UUID] = mapped_column(
        uid_fk_type(), primary_key=True, default=uuid.uuid4
    )
    user_uid: Mapped[uuid.UUID] = mapped_column(uid_fk_type(), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Message(Base):
    """One turn. ``role`` is "user" for the human and "ai" for the assistant."""

    __tablename__ = "message"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_uid: Mapped[uuid.UUID] = mapped_column(
        uid_fk_type(),
        ForeignKey("session.session_uid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[Session] = relationship(back_populates="messages")
