"""Settings for the terminal client.

Standalone on purpose — the server's Dynaconf configuration demands a database
URL and a broker, neither of which a chat client should need.
"""

import os
import uuid
from dataclasses import dataclass, field

DEFAULT_BASE_URL = "http://localhost:8080/v1"
DEFAULT_MODEL = "baymax"


@dataclass
class Settings:
    """Everything the client needs to reach an endpoint and hold a conversation."""

    base_url: str = field(default_factory=lambda: os.environ.get("BAYMAX_URL", DEFAULT_BASE_URL))
    api_key: str = field(default_factory=lambda: os.environ.get("BAYMAX_API_KEY", "not-needed"))
    model: str = field(default_factory=lambda: os.environ.get("BAYMAX_MODEL", DEFAULT_MODEL))
    timeout: float = 300.0
    #: Sent on every request so the server ties the turns into one conversation
    #: and persists them together.
    session_uid: uuid.UUID = field(default_factory=uuid.uuid4)
    user: str | None = None
    markdown: bool = True

    @property
    def completions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    @property
    def models_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/models"
