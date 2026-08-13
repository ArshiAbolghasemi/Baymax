"""Chat configuration.

Only conversation behaviour lives here. The database connection comes from
:class:`~baymax.db.config.DatabaseConfig` and the model endpoint from
:class:`~baymax.clients.config.LLMConfig`, because chat owns neither.
"""

from dynaconf import Dynaconf

from baymax.common.env import dynaconf_kwargs


class ChatConfig(Dynaconf):
    """How the assistant behaves in a conversation."""

    def __init__(self) -> None:
        super().__init__(**dynaconf_kwargs())

    @property
    def system_prompt(self) -> str:
        return str(
            self.get(
                "CHAT_SYSTEM_PROMPT",
                "You are Baymax, a careful medical assistant. Answer clearly and "
                "concisely. Recommend seeing a clinician for anything urgent, and "
                "never invent facts you are not sure of.",
            )
        )

    @property
    def history_limit(self) -> int:
        """How many past turns to replay to the model."""
        return int(self.get("CHAT_HISTORY_LIMIT", 20))
