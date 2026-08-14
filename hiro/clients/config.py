"""Configuration for the external services Baymax talks to."""

from dynaconf import Dynaconf, Validator

from common.env import dynaconf_kwargs


class EmbeddingConfig(Dynaconf):
    """OpenAI-compatible embedding endpoint (vLLM serving bge-m3 here)."""

    def __init__(self) -> None:
        super().__init__(
            **dynaconf_kwargs(
                [
                    Validator("EMBEDDING_BASE_URL", must_exist=True, is_type_of=str),
                    Validator("EMBEDDING_MODEL", must_exist=True, is_type_of=str),
                ]
            )
        )

    @property
    def base_url(self) -> str:
        return str(self.get("EMBEDDING_BASE_URL"))

    @property
    def model(self) -> str:
        return str(self.get("EMBEDDING_MODEL"))

    @property
    def api_key(self) -> str:
        """vLLM ignores this, but the OpenAI client refuses to start without one."""
        return str(self.get("EMBEDDING_API_KEY", "not-needed"))

    @property
    def timeout(self) -> float:
        return float(self.get("EMBEDDING_TIMEOUT", 60))

    @property
    def max_retries(self) -> int:
        return int(self.get("EMBEDDING_MAX_RETRIES", 3))

    @property
    def batch_size(self) -> int:
        return int(self.get("EMBEDDING_BATCH_SIZE", 32))

    @property
    def dimensions(self) -> int:
        """Vector width the model emits — bge-m3 is 1024.

        Lives here rather than with Qdrant because it is a property of the
        model; collections are created to match it.
        """
        return int(self.get("EMBEDDING_DIMENSIONS", 1024))


class QdrantConfig(Dynaconf):
    """Qdrant connection settings. Collection names belong to the domains."""

    def __init__(self) -> None:
        super().__init__(**dynaconf_kwargs([Validator("QDRANT_URL", must_exist=True)]))

    @property
    def url(self) -> str:
        return str(self.get("QDRANT_URL"))

    @property
    def api_key(self) -> str | None:
        return str(self.get("QDRANT_API_KEY", "")) or None

    @property
    def timeout(self) -> int:
        return int(self.get("QDRANT_TIMEOUT", 30))

    @property
    def prefer_grpc(self) -> bool:
        return bool(self.get("QDRANT_PREFER_GRPC", False))

    @property
    def distance(self) -> str:
        return str(self.get("QDRANT_DISTANCE", "Cosine"))


class ChatbotConfig(Dynaconf):
    """Generative model endpoint, OpenAI-compatible (vLLM serving MedGemma).

    Separate from :class:`EmbeddingConfig`: the two are different models, often
    on different ports, and are scaled independently.
    """

    def __init__(self) -> None:
        super().__init__(**dynaconf_kwargs())

    @property
    def base_url(self) -> str:
        return str(self.get("CHATBOT_BASE_URL", "http://localhost:8000/v1"))

    @property
    def model(self) -> str:
        return str(self.get("CHATBOT_MODEL", "medgemma-4b"))

    @property
    def api_key(self) -> str:
        """vLLM ignores this, but the OpenAI client refuses to start without one."""
        return str(self.get("CHATBOT_API_KEY", "not-needed"))

    @property
    def timeout(self) -> float:
        return float(self.get("CHATBOT_TIMEOUT", 300))

    @property
    def max_retries(self) -> int:
        """Retries performed by the OpenAI client for transient request failures."""
        return int(self.get("CHATBOT_MAX_RETRIES", 2))

    @property
    def temperature(self) -> float:
        return float(self.get("CHATBOT_TEMPERATURE", 0.7))

    @property
    def max_tokens(self) -> int:
        return int(self.get("CHATBOT_MAX_TOKENS", 1024))


class GuardrailConfig(Dynaconf):
    """Independent OpenAI-compatible model used for topic classification.

    Connection settings inherit their ``CHATBOT_*`` counterparts when a dedicated
    ``GUARDRAIL_*`` variable is omitted. Classification behavior keeps its
    deterministic low-token defaults while remaining fully configurable.
    """

    def __init__(self) -> None:
        super().__init__(**dynaconf_kwargs())

    @property
    def base_url(self) -> str:
        return str(
            self.get(
                "GUARDRAIL_BASE_URL",
                self.get("CHATBOT_BASE_URL", "http://localhost:8000/v1"),
            )
        )

    @property
    def model(self) -> str:
        return str(
            self.get(
                "GUARDRAIL_MODEL",
                self.get("CHATBOT_MODEL", "medgemma-4b"),
            )
        )

    @property
    def api_key(self) -> str:
        return str(
            self.get(
                "GUARDRAIL_API_KEY",
                self.get("CHATBOT_API_KEY", "not-needed"),
            )
        )

    @property
    def timeout(self) -> float:
        return float(
            self.get(
                "GUARDRAIL_TIMEOUT",
                self.get("CHATBOT_TIMEOUT", 300),
            )
        )

    @property
    def max_retries(self) -> int:
        return int(
            self.get(
                "GUARDRAIL_MAX_RETRIES",
                self.get("CHATBOT_MAX_RETRIES", 2),
            )
        )

    @property
    def temperature(self) -> float:
        return float(self.get("GUARDRAIL_TEMPERATURE", 0))

    @property
    def max_tokens(self) -> int:
        return int(self.get("GUARDRAIL_MAX_TOKENS", 4))
