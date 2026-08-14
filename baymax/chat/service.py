"""Chat orchestration.

The server owns both turns of the conversation: the user message is persisted
the moment it arrives, and the assistant message once its stream completes. The
client never sends the assistant text back to be stored.
"""

import time
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
    logger.debug("chat history requested session_uid=%s", session_uid)
    if await repo.get_session(session, session_uid) is None:
        logger.warning("chat history session not found session_uid=%s", session_uid)
        msg = f"session {session_uid} not found"
        raise SessionNotFoundError(msg)
    messages = await repo.list_messages(session, session_uid)
    logger.info("chat history loaded session_uid=%s messages=%d", session_uid, len(messages))
    return messages


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
        logger.warning("user message rejected session not found session_uid=%s", session_uid)
        msg = f"session {session_uid} not found"
        raise SessionNotFoundError(msg)

    await repo.add_message(session, session_uid, "user", content)
    logger.info("stored user message on session %s (%d chars)", session_uid, len(content))
    return row.user_uid


def ensure_connected(user_uid: uuid.UUID) -> None:
    """Step 2: the socket must already be open, or there is nowhere to stream."""
    if not connections.is_connected(user_uid):
        logger.warning("chat stream rejected no socket user_uid=%s", user_uid)
        msg = "no active websocket connection"
        raise NoConnectionError(msg)
    logger.debug("chat socket available user_uid=%s", user_uid)


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
    delivered_chunks = 0
    started = time.perf_counter()
    logger.info(
        "reply stream started session_uid=%s user_uid=%s question_chars=%d",
        session_uid,
        user_uid,
        len(question),
    )
    try:
        async for chunk in stream_answer(question, session_uid):
            chunks.append(chunk)
            frame = TokenFrame(session_uid=session_uid, data=chunk)
            if not await connections.send(user_uid, frame.model_dump(mode="json")):
                # Socket died mid-stream. Stop generating rather than talking to
                # nobody; what was produced is still persisted below.
                logger.info("socket closed mid-stream for session %s", session_uid)
                break
            delivered_chunks += 1
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

    done_delivered = await connections.send(
        user_uid, DoneFrame(session_uid=session_uid).model_dump(mode="json")
    )
    elapsed = (time.perf_counter() - started) * 1_000
    logger.info(
        "reply stream finished session_uid=%s chunks=%d reply_chars=%d done_delivered=%s "
        "elapsed_ms=%.1f",
        session_uid,
        delivered_chunks,
        len(reply),
        done_delivered,
        elapsed,
    )
