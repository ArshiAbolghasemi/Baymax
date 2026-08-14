"""OpenAI-compatible request and response contracts for the chat agent."""

import uuid
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


class ChatCompletionRequest(BaseModel):
    """OpenAI chat-completions input plus optional conversation identifiers."""

    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1, max_length=256)
    messages: list[ChatMessage] = Field(min_length=1, max_length=1_024)
    stream: bool = False
    user: str | None = Field(default=None, max_length=512)
    session_uid: uuid.UUID | None = None
    chat_id: str | None = Field(default=None, max_length=512)

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
