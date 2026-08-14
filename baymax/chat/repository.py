"""Data access for chat. Functions never commit — the caller owns the transaction."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from baymax.chat.models import Message, Session


async def create_session(session: AsyncSession, user_uid: uuid.UUID) -> Session:
    row = Session(user_uid=user_uid)
    session.add(row)
    await session.flush()
    return row


async def get_session(session: AsyncSession, session_uid: uuid.UUID) -> Session | None:
    return await session.get(Session, session_uid)


async def add_message(
    session: AsyncSession, session_uid: uuid.UUID, role: str, content: str
) -> Message:
    row = Message(session_uid=session_uid, role=role, content=content)
    session.add(row)
    await session.flush()
    return row


async def list_messages(
    session: AsyncSession, session_uid: uuid.UUID, *, limit: int | None = None
) -> list[Message]:
    """History oldest-first.

    Ordered by id as well as created_at: SQLite timestamps are coarse enough
    that two turns in the same second would otherwise come back in any order.
    """
    statement = (
        select(Message)
        .where(Message.session_uid == session_uid)
        .order_by(Message.created_at, Message.id)
    )
    rows = list((await session.scalars(statement)).all())
    return rows[-limit:] if limit else rows


async def list_recent_user_messages(
    session: AsyncSession, session_uid: uuid.UUID, *, limit: int = 5
) -> list[Message]:
    """The user's previous questions, oldest first.

    Offset by one: the turn that triggered this run has already been stored, and
    feeding the question back as its own history is noise.
    """
    statement = (
        select(Message)
        .where(Message.session_uid == session_uid, Message.role == "user")
        .order_by(Message.created_at.desc(), Message.id.desc())
        .offset(1)
        .limit(limit)
    )
    rows = list((await session.scalars(statement)).all())
    return list(reversed(rows))
