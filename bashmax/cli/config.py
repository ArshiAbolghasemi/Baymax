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
    #: The conversation, as opened by POST /v1/sessions. None until then: the
    #: server no longer accepts a uid it has never heard of, so inventing one
    #: here would only produce a 404 on the first question.
    session_uid: uuid.UUID | None = None
    user: str | None = None
    markdown: bool = True

    @property
    def sessions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/sessions"

    @property
    def completions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    @property
    def models_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/models"
