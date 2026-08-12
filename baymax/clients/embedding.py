"""Embedding client speaking the OpenAI ``/v1/embeddings`` protocol.

Points at any compatible server; in this project that is vLLM serving bge-m3.
"""

from collections.abc import Sequence
from functools import lru_cache

from openai import OpenAI

from baymax.common.logging import get_logger, log_duration
from baymax.config import get_config

logger = get_logger(__name__)


class EmbeddingError(RuntimeError):
    """Raised when the embedding backend returns something unusable."""


class EmbeddingClient:
    """Thin, batching wrapper over an OpenAI-compatible embeddings endpoint."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float,
        max_retries: int,
        batch_size: int,
        dimensions: int,
    ) -> None:
        self._model = model
        self._batch_size = batch_size
        self._dimensions = dimensions
        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
        )
        logger.info(
            "embedding client ready model=%s base_url=%s batch_size=%d dim=%d",
            model,
            base_url,
            batch_size,
            dimensions,
        )

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed texts, preserving input order. Empty input yields empty output."""
        if not texts:
            logger.debug("embed called with no texts")
            return []

        batches = (len(texts) + self._batch_size - 1) // self._batch_size
        vectors: list[list[float]] = []
        with log_duration(logger, "embed", model=self._model, texts=len(texts), batches=batches):
            for index, start in enumerate(range(0, len(texts), self._batch_size), start=1):
                batch = list(texts[start : start + self._batch_size])
                logger.debug("embedding batch %d/%d size=%d", index, batches, len(batch))
                vectors.extend(self._embed_batch(batch))

        if len(vectors) != len(texts):
            logger.error("embedding count mismatch expected=%d got=%d", len(texts), len(vectors))
            msg = f"expected {len(texts)} embeddings, got {len(vectors)}"
            raise EmbeddingError(msg)

        # A model swap that changes width would otherwise fail deep inside
        # Qdrant with a far less obvious error.
        if len(vectors[0]) != self._dimensions:
            logger.error(
                "embedding width mismatch model=%s expected=%d got=%d",
                self._model,
                self._dimensions,
                len(vectors[0]),
            )
            msg = (
                f"model {self._model} returned {len(vectors[0])}-dim vectors, "
                f"configured for {self._dimensions} (set EMBEDDING_DIMENSIONS)"
            )
            raise EmbeddingError(msg)

        logger.debug("embedded %d text(s) dim=%d", len(vectors), len(vectors[0]))
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self._model, input=batch)
        # The spec allows results out of order; sort by index before unpacking.
        ordered = sorted(response.data, key=lambda item: item.index)
        return [list(item.embedding) for item in ordered]


@lru_cache(maxsize=1)
def get_embedding_client() -> EmbeddingClient:
    config = get_config().embedding
    return EmbeddingClient(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        timeout=config.timeout,
        max_retries=config.max_retries,
        batch_size=config.batch_size,
        dimensions=config.dimensions,
    )
