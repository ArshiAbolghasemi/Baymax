"""The application's composed configuration.

Each package owns a config class that reads its own environment variables;
this module assembles them into one immutable object. Consumers do::

    from hiro.config import get_config

    config = get_config()
    config.database.url
    config.knowledge_base.collection

Only leaf ``<package>.config`` modules are imported here, so composing the root
config never pulls in a package's runtime code.
"""

from dataclasses import dataclass
from functools import lru_cache

from dynaconf import Dynaconf

from hiro.api.config import ApiConfig
from hiro.chat.config import ChatConfig, McpConfig
from hiro.clients.config import ChatbotConfig, EmbeddingConfig, GuardrailConfig, QdrantConfig
from hiro.common.env import dynaconf_kwargs
from hiro.db.config import DatabaseConfig
from hiro.knowledge_base.config import KnowledgeBaseConfig
from hiro.worker.config import CeleryConfig

DEFAULT_LOG_FORMAT = (
    "{time:YYYY-MM-DDTHH:mm:ss.SSSZ} | {level:<8} | "
    "[{extra[correlation_id]}] | {extra[component]} | {message}"
)

# Libraries too chatty to leave at our root level. The openai SDK vendors its
# transport under the *2 names; without those entries DEBUG drowns in
# per-connection socket chatter.
DEFAULT_LIBRARY_LEVELS = {
    "sqlalchemy.engine": "WARNING",
    "httpx": "WARNING",
    "httpcore": "WARNING",
    "httpx2": "WARNING",
    "httpcore2": "WARNING",
    "openai": "WARNING",
    "urllib3": "WARNING",
    "uvicorn.access": "WARNING",
    "celery.app.trace": "WARNING",
}


class LoggingConfig(Dynaconf):
    """Logging settings — cross-cutting, so owned by the root config."""

    def __init__(self) -> None:
        super().__init__(**dynaconf_kwargs())

    @property
    def level(self) -> str:
        return str(self.get("LOG_LEVEL", "INFO")).upper()

    @property
    def format(self) -> str:
        return str(self.get("LOG_FORMAT", DEFAULT_LOG_FORMAT))

    @property
    def library_levels(self) -> dict[str, str]:
        """Per-logger overrides. Override wholesale with ``LOG_LIBRARY_LEVELS``
        as a JSON object, e.g. ``@json {"httpx": "DEBUG"}``.
        """
        override = self.get("LOG_LIBRARY_LEVELS", None)
        if not override:
            return dict(DEFAULT_LIBRARY_LEVELS)
        return {str(name): str(level).upper() for name, level in dict(override).items()}


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Every package's configuration, in one place."""

    api: ApiConfig
    logging: LoggingConfig
    chat: ChatConfig
    mcp: McpConfig
    database: DatabaseConfig
    celery: CeleryConfig
    embedding: EmbeddingConfig
    chatbot: ChatbotConfig
    guardrail: GuardrailConfig
    qdrant: QdrantConfig
    knowledge_base: KnowledgeBaseConfig


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Build (once) the configuration for this process."""
    return AppConfig(
        api=ApiConfig(),
        logging=LoggingConfig(),
        chat=ChatConfig(),
        mcp=McpConfig(),
        database=DatabaseConfig(),
        celery=CeleryConfig(),
        embedding=EmbeddingConfig(),
        chatbot=ChatbotConfig(),
        guardrail=GuardrailConfig(),
        qdrant=QdrantConfig(),
        knowledge_base=KnowledgeBaseConfig(),
    )
