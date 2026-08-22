"""Transport-independent orchestration for OpenAI-compatible chat requests."""

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from hiro.chat import repository as repo
from hiro.chat.agent.graph import stream_answer
from hiro.chat.schemas import ChatCompletionRequest
from hiro.chat.session_resolution import ResolvedSession, resolve_session
from hiro.common.logging import get_logger
from hiro.db.session import async_session_scope

logger = get_logger(__name__)

MAX_MESSAGE_CHARS = 32_000


class InvalidConversationError(ValueError):
    """The request has no usable user turn."""


class SessionOwnershipError(PermissionError):
    """An explicit conversation belongs to a different user identity."""


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
    """Resolve/create the conversation and persist only its newest user turn.

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
    resolved: ResolvedSession = resolve_session(
        payload,
        header_session_uid=header_session_uid,
        first_user_message=user_messages[0],
    )
    row = await repo.get_session_for_update(session, resolved.session_uid)
    if row is None:
        row = await repo.create_session(
            session,
            resolved.user_uid,
            session_uid=resolved.session_uid,
        )
        logger.info(
            "chat session created session_uid=%s user_uid=%s resolution=%s",
            resolved.session_uid,
            resolved.user_uid,
            resolved.source,
        )
    elif row.user_uid != resolved.user_uid:
        logger.warning(
            "chat session ownership mismatch session_uid=%s resolved_user_uid=%s",
            resolved.session_uid,
            resolved.user_uid,
        )
        raise SessionOwnershipError("session_uid belongs to a different user")

    latest = await repo.get_latest_message(session, resolved.session_uid)
    duplicate_unanswered_turn = bool(
        latest is not None and latest.role == "user" and latest.content == question
    )
    if duplicate_unanswered_turn:
        logger.info(
            "duplicate unanswered user turn skipped session_uid=%s question_chars=%d",
            resolved.session_uid,
            len(question),
        )
    else:
        await repo.add_message(session, resolved.session_uid, "user", question)
        logger.info(
            "user turn stored session_uid=%s question_chars=%d",
            resolved.session_uid,
            len(question),
        )

    return PreparedTurn(
        session_uid=resolved.session_uid,
        user_uid=resolved.user_uid,
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


async def stream_reply(turn: PreparedTurn) -> AsyncIterator[str]:
    """Run the shared agent graph, stream chunks, then persist a complete reply."""
    chunks: list[str] = []
    completed = False
    started = time.perf_counter()
    logger.info(
        "chat generation started session_uid=%s question_chars=%d",
        turn.session_uid,
        len(turn.question),
    )
    try:
        async for chunk in stream_answer(turn.question, turn.session_uid):
            chunks.append(chunk)
            yield chunk
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
    """Collect the same persisted stream for a non-streaming client."""
    return "".join([chunk async for chunk in stream_reply(turn)])
