"""Which conversation a request is for, and whose it is.

Nothing here invents a conversation. A session is created once, explicitly,
through ``POST /v1/sessions``; a completion names one that already exists.
Deriving a session uid from the message text instead — which this module used
to do — meant a typo silently started a second conversation, and two people
asking the same first question shared one.
"""

import uuid

from hiro.chat.schemas import ChatCompletionRequest
from hiro.common.logging import get_logger
from hiro.config import get_config

logger = get_logger(__name__)

ANONYMOUS = "user:anonymous"


def derive_user_uid(user: str | None) -> uuid.UUID:
    """Turn a client's identity string into a stable uuid.

    A uuid is taken as-is so a caller that already has one keeps it; anything
    else is hashed under the configured namespace. No identity at all is a
    single shared anonymous user, which is what a client with no login has.
    """
    namespace = get_config().chat.session_namespace
    if not user:
        return uuid.uuid5(namespace, ANONYMOUS)
    try:
        return uuid.UUID(user)
    except ValueError:
        return uuid.uuid5(namespace, f"user:{user}")


def resolve_session_uid(
    payload: ChatCompletionRequest,
    *,
    header_session_uid: uuid.UUID | None,
) -> uuid.UUID | None:
    """The conversation this request names: header first, then body.

    ``None`` means the client named none, which is a client error rather than
    an invitation to make one up.
    """
    session_uid = header_session_uid or payload.session_uid
    if session_uid is None:
        return None
    logger.debug(
        "chat session named session_uid=%s source=%s",
        session_uid,
        "header" if header_session_uid else "body",
    )
    return session_uid
