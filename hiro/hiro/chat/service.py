"""Transport-independent orchestration for OpenAI-compatible chat requests."""

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from hiro.chat import repository as repo
from hiro.chat.agent.events import AgentEvent, TextDelta
from hiro.chat.agent.graph import stream_answer
from hiro.chat.models import Session
from hiro.chat.schemas import ChatCompletionRequest, SessionCreate
from hiro.chat.session_resolution import derive_user_uid, resolve_session_uid
from hiro.common.logging import get_logger
from hiro.db.session import async_session_scope

logger = get_logger(__name__)

MAX_MESSAGE_CHARS = 32_000


class InvalidConversationError(ValueError):
    """The request has no usable user turn, or names no conversation."""


class UnknownSessionError(LookupError):
    """The named conversation does not exist. Open one with POST /v1/sessions."""


class SessionOwnershipError(PermissionError):
    """An explicit conversation belongs to a different user identity."""


async def create_session(session: AsyncSession, payload: SessionCreate) -> Session:
    """Open a conversation. The only place a session row is ever created."""
    row = await repo.create_session(session, derive_user_uid(payload.user))
    logger.info(
        "chat session created session_uid=%s user_uid=%s identified=%s",
        row.session_uid,
        row.user_uid,
        bool(payload.user),
    )
    return row


@dataclass(frozen=True, slots=True)
class PreparedTurn:
    session_uid: uuid.UUID
    user_uid: uuid.UUID
    question: str
    user_message_stored: bool


async def store_user_message(
    session: AsyncSession,
    payload: ChatCompletionRequest,
    *,
    header_session_uid: uuid.UUID | None,
) -> PreparedTurn:
    """Persist the newest user turn of an existing conversation.

    The conversation must already exist: this never creates one, so a client
    that forgets to open a session is told so rather than quietly starting a
    fresh conversation on every turn.

    A locked existing session makes the regenerate check and insert one
    transaction. If the last stored row is the same unanswered user turn, the
    insert is skipped; replayed client history is never copied into our tables.
    """
    user_messages = payload.user_messages()
    if not user_messages:
        raise InvalidConversationError("messages must contain a non-empty user message")
    if any(len(message) > MAX_MESSAGE_CHARS for message in user_messages):
        raise InvalidConversationError(
            f"user message content must not exceed {MAX_MESSAGE_CHARS} characters"
        )

    question = user_messages[-1]
    session_uid = resolve_session_uid(payload, header_session_uid=header_session_uid)
    if session_uid is None:
        raise InvalidConversationError(
            "no conversation named; open one with POST /v1/sessions and send it "
            "as X-Session-UID or session_uid"
        )

    row = await repo.get_session_for_update(session, session_uid)
    if row is None:
        logger.warning("chat session not found session_uid=%s", session_uid)
        raise UnknownSessionError(f"session {session_uid} does not exist")

    # Ownership is only checked when the client says who it is; a session
    # opened for a named user is not readable by another named user.
    if payload.user and row.user_uid != derive_user_uid(payload.user):
        logger.warning(
            "chat session ownership mismatch session_uid=%s",
            session_uid,
        )
        raise SessionOwnershipError("session_uid belongs to a different user")

    latest = await repo.get_latest_message(session, session_uid)
    duplicate_unanswered_turn = bool(
        latest is not None and latest.role == "user" and latest.content == question
    )
    if duplicate_unanswered_turn:
        logger.info(
            "duplicate unanswered user turn skipped session_uid=%s question_chars=%d",
            session_uid,
            len(question),
        )
    else:
        await repo.add_message(session, session_uid, "user", question)
        logger.info(
            "user turn stored session_uid=%s question_chars=%d",
            session_uid,
            len(question),
        )

    return PreparedTurn(
        session_uid=session_uid,
        user_uid=row.user_uid,
        question=question,
        user_message_stored=not duplicate_unanswered_turn,
    )


async def _store_assistant_message(session_uid: uuid.UUID, content: str) -> None:
    async with async_session_scope() as session:
        await repo.add_message(session, session_uid, "ai", content)
    logger.info(
        "assistant turn stored session_uid=%s response_chars=%d",
        session_uid,
        len(content),
    )


async def stream_reply(turn: PreparedTurn) -> AsyncIterator[AgentEvent]:
    """Run the shared agent graph, stream its events, then persist the reply.

    Only text is persisted: a tool call is how an answer was reached, not part
    of the answer a client replays as history.
    """
    chunks: list[str] = []
    completed = False
    started = time.perf_counter()
    logger.info(
        "chat generation started session_uid=%s question_chars=%d",
        turn.session_uid,
        len(turn.question),
    )
    try:
        async for event in stream_answer(turn.question, turn.session_uid):
            if isinstance(event, TextDelta):
                chunks.append(event.text)
            yield event
        completed = True
    except Exception:
        logger.exception("chat generation failed session_uid=%s", turn.session_uid)
        raise
    finally:
        reply = "".join(chunks)
        if completed and reply:
            try:
                await _store_assistant_message(turn.session_uid, reply)
            except Exception:
                logger.exception(
                    "assistant persistence failed session_uid=%s response_chars=%d",
                    turn.session_uid,
                    len(reply),
                )
                raise
        elif not completed:
            logger.warning(
                "incomplete assistant turn not stored session_uid=%s partial_chars=%d",
                turn.session_uid,
                len(reply),
            )
        else:
            logger.warning("empty assistant turn not stored session_uid=%s", turn.session_uid)

        elapsed = (time.perf_counter() - started) * 1_000
        logger.info(
            "chat generation finished session_uid=%s completed=%s chunks=%d "
            "response_chars=%d elapsed_ms=%.1f",
            turn.session_uid,
            completed,
            len(chunks),
            len(reply),
            elapsed,
        )


async def answer(turn: PreparedTurn) -> str:
    """Collect the same persisted stream for a non-streaming client.

    Tool activity is dropped: a single JSON response has nowhere to put it.
    """
    return "".join(
        [event.text async for event in stream_reply(turn) if isinstance(event, TextDelta)]
    )
