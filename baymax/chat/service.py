"""Chat orchestration.

The server owns both turns of the conversation: the user message is persisted
the moment it arrives, and the assistant message once its stream completes. The
client never sends the assistant text back to be stored.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from baymax.chat import repository as repo
from baymax.chat.agent.graph import stream_answer
from baymax.chat.connections import connections
from baymax.chat.models import Message
from baymax.chat.schemas import DoneFrame, ErrorFrame, TokenFrame
from baymax.common.logging import get_logger
from baymax.db.session import async_session_scope

logger = get_logger(__name__)


class SessionNotFoundError(LookupError):
    """No session with that uid."""


class NoConnectionError(RuntimeError):
    """The user has no registered WebSocket to stream into."""


async def create_session(session: AsyncSession, user_uid: uuid.UUID) -> uuid.UUID:
    row = await repo.create_session(session, user_uid)
    logger.info("created session %s for user %s", row.session_uid, user_uid)
    return row.session_uid


async def get_history(session: AsyncSession, session_uid: uuid.UUID) -> list[Message]:
    if await repo.get_session(session, session_uid) is None:
        msg = f"session {session_uid} not found"
        raise SessionNotFoundError(msg)
    return await repo.list_messages(session, session_uid)


async def store_user_message(
    session: AsyncSession, session_uid: uuid.UUID, content: str
) -> uuid.UUID:
    """Step 1: persist the user turn. Returns the session's owner.

    The caller commits immediately afterwards, before the socket is checked, so
    that a 409 cannot roll this away. The turn is the user's — it should survive
    a missing socket or a failed generation.
    """
    row = await repo.get_session(session, session_uid)
    if row is None:
        msg = f"session {session_uid} not found"
        raise SessionNotFoundError(msg)

    await repo.add_message(session, session_uid, "user", content)
    logger.info("stored user message on session %s (%d chars)", session_uid, len(content))
    return row.user_uid


def ensure_connected(user_uid: uuid.UUID) -> None:
    """Step 2: the socket must already be open, or there is nowhere to stream."""
    if not connections.is_connected(user_uid):
        msg = "no active websocket connection"
        raise NoConnectionError(msg)


async def stream_reply(
    session_uid: uuid.UUID,
    user_uid: uuid.UUID,
    question: str,
) -> None:
    """Steps 3 and 4: stream the reply down the socket, then persist it.

    The reply is produced by the agent workflow in :mod:`baymax.chat.agent`,
    which guards the topic, retrieves context and generates. This function only
    moves the resulting chunks onto the socket and stores the finished turn.

    Runs after the 202 has been sent, so it opens its own database session
    rather than borrowing the request's.
    """
    chunks: list[str] = []
    try:
        async for chunk in stream_answer(question, session_uid):
            chunks.append(chunk)
            frame = TokenFrame(session_uid=session_uid, data=chunk)
            if not await connections.send(user_uid, frame.model_dump(mode="json")):
                # Socket died mid-stream. Stop generating rather than talking to
                # nobody; what was produced is still persisted below.
                logger.info("socket closed mid-stream for session %s", session_uid)
                break
    except Exception as exc:
        logger.exception("generation failed for session %s", session_uid)
        await connections.send(
            user_uid,
            ErrorFrame(session_uid=session_uid, data=f"{type(exc).__name__}: {exc}").model_dump(
                mode="json"
            ),
        )

    reply = "".join(chunks)
    if reply:
        async with async_session_scope() as session:
            await repo.add_message(session, session_uid, "ai", reply)
        logger.info("stored ai message on session %s (%d chars)", session_uid, len(reply))
    else:
        logger.warning("no text generated for session %s, nothing stored", session_uid)

    await connections.send(user_uid, DoneFrame(session_uid=session_uid).model_dump(mode="json"))
