"""OpenAI-compatible request and response contracts for the chat agent."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    """One client transcript item.

    Extra OpenAI fields are accepted so clients may replay assistant/tool
    messages without this endpoint rejecting otherwise valid requests.
    """

    model_config = ConfigDict(extra="allow")

    role: Literal["system", "user", "assistant", "tool", "developer"]
    content: str | list[dict[str, Any]] | None = None

    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content.strip()
        if not isinstance(self.content, list):
            return ""
        parts: list[str] = []
        for part in self.content:
            if part.get("type") not in {"text", "input_text"}:
                continue
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "\n".join(parts).strip()


class SessionCreate(BaseModel):
    """Open a conversation. Everything about it is optional."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"user": "arshia@example.com"}]},
    )

    user: str | None = Field(
        default=None,
        max_length=512,
        description=(
            "Client-side identity for the person. A uuid is used as-is; any "
            "other string is hashed into a stable uuid. Omitted means anonymous."
        ),
    )


class SessionRead(BaseModel):
    """A conversation that now exists."""

    session_uid: uuid.UUID
    user_uid: uuid.UUID
    created_at: datetime


class ChatCompletionRequest(BaseModel):
    """OpenAI chat-completions input, for a conversation that already exists."""

    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1, max_length=256)
    messages: list[ChatMessage] = Field(min_length=1, max_length=1_024)
    stream: bool = False
    user: str | None = Field(default=None, max_length=512)
    session_uid: uuid.UUID | None = Field(
        default=None,
        description="The conversation from POST /v1/sessions. X-Session-UID wins over this.",
    )

    def user_messages(self) -> list[str]:
        return [
            text for message in self.messages if message.role == "user" and (text := message.text())
        ]


class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class CompletionChoice(BaseModel):
    index: int = 0
    message: AssistantMessage
    finish_reason: Literal["stop"] = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[CompletionChoice]


class ModelInfo(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = 0
    owned_by: str = "baymax"


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelInfo]
