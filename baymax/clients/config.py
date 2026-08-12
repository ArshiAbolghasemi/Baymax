"""Configuration for the external services Baymax talks to."""

from dynaconf import Dynaconf, Validator

from baymax.common.env import dynaconf_kwargs


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
