"""Request/response and WebSocket frame contracts for chat."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MessageText = Annotated[str, Field(min_length=1, max_length=32_000)]


class SessionCreate(BaseModel):
    user_uid: uuid.UUID


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_uid: uuid.UUID


class MessageCreate(BaseModel):
    content: MessageText


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_uid: uuid.UUID
    role: str
    content: str
    created_at: datetime


class StreamAccepted(BaseModel):
    """Body of the 202. The reply itself arrives on the WebSocket."""

    status: Literal["streaming"] = "streaming"


class TokenFrame(BaseModel):
    """One chunk of the reply.

    ``session_uid`` is on every frame because a user has a single socket that may
    be receiving streams for several sessions at once.
    """

    session_uid: uuid.UUID
    type: Literal["token"] = "token"
    data: str


class DoneFrame(BaseModel):
    """Sent once the reply is complete and persisted."""

    session_uid: uuid.UUID
    type: Literal["done"] = "done"


class ErrorFrame(BaseModel):
    """Sent if generation fails part-way; the stream ends here."""

    session_uid: uuid.UUID
    type: Literal["error"] = "error"
    data: str
