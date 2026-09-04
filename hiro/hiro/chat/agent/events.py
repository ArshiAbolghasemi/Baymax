"""What a running agent emits, before any transport decides how to encode it.

The workflow yields these; the router turns them into SSE frames and the
service persists only the text. Keeping them plain objects is what lets those
two disagree about encoding without either reaching into the graph.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TextDelta:
    """A piece of the assistant's reply, as generated."""

    text: str


@dataclass(frozen=True, slots=True)
class ToolCall:
    """The model asked for a tool. Emitted before the tool has run."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What the tool answered, as the model will see it."""

    tool_call_id: str
    name: str
    content: str


AgentEvent = TextDelta | ToolCall | ToolResult
