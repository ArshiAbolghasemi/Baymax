"""Data access for chat. Functions never commit — the caller owns the transaction."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from baymax.chat.models import Message, Session


async def create_session(
    session: AsyncSession,
    user_uid: uuid.UUID,
    *,
    session_uid: uuid.UUID | None = None,
) -> Session:
    row = Session(user_uid=user_uid, **({"session_uid": session_uid} if session_uid else {}))
    session.add(row)
    await session.flush()
    return row


async def get_session_for_update(session: AsyncSession, session_uid: uuid.UUID) -> Session | None:
    statement = select(Session).where(Session.session_uid == session_uid).with_for_update()
    return await session.scalar(statement)


async def add_message(
    session: AsyncSession, session_uid: uuid.UUID, role: str, content: str
) -> Message:
    row = Message(session_uid=session_uid, role=role, content=content)
    session.add(row)
    await session.flush()
    return row


async def get_latest_message(session: AsyncSession, session_uid: uuid.UUID) -> Message | None:
    statement = (
        select(Message)
        .where(Message.session_uid == session_uid)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
    )
    return await session.scalar(statement)


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
