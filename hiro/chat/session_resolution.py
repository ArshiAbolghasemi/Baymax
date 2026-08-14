"""Stable conversation and user identity resolution for stateless clients."""

import uuid
from dataclasses import dataclass
from typing import Literal

from chat.schemas import ChatCompletionRequest
from common.logging import get_logger
from config import get_config

logger = get_logger(__name__)

ResolutionSource = Literal["header", "body", "chat_id", "derived"]


@dataclass(frozen=True, slots=True)
class ResolvedSession:
    session_uid: uuid.UUID
    user_uid: uuid.UUID
    source: ResolutionSource


def _user_uid(user: str | None, namespace: uuid.UUID) -> uuid.UUID:
    if user:
        try:
            return uuid.UUID(user)
        except ValueError:
            return uuid.uuid5(namespace, f"user:{user}")
    return uuid.uuid5(namespace, "user:anonymous")


def resolve_session(
    payload: ChatCompletionRequest,
    *,
    header_session_uid: uuid.UUID | None,
    first_user_message: str,
) -> ResolvedSession:
    """Resolve header → body → client chat id → deterministic fallback."""
    config = get_config().chat
    namespace = config.session_namespace
    user_uid = _user_uid(payload.user, namespace)

    if header_session_uid is not None:
        session_uid = header_session_uid
        source: ResolutionSource = "header"
    elif payload.session_uid is not None:
        session_uid = payload.session_uid
        source = "body"
    elif payload.chat_id:
        session_uid = uuid.uuid5(namespace, f"chat:{user_uid}:{payload.chat_id}")
        source = "chat_id"
    else:
        session_uid = uuid.uuid5(namespace, f"conversation:{user_uid}:{first_user_message}")
        source = "derived"

    logger.info(
        "chat session resolved session_uid=%s user_uid=%s source=%s",
        session_uid,
        user_uid,
        source,
    )
    return ResolvedSession(session_uid=session_uid, user_uid=user_uid, source=source)
