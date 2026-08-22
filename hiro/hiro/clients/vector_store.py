"""Qdrant access.

The client is connection-level infrastructure; which collection to use is the
caller's decision, so :func:`get_vector_store` takes it as an argument rather
than reading a domain's config.
"""

import uuid
from collections.abc import Sequence
from functools import cache, lru_cache
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from hiro.common.logging import get_logger, log_duration
from hiro.config import get_config

logger = get_logger(__name__)


class VectorStore:
    """Owns a Qdrant collection and the writes into it."""

    def __init__(
        self,
        client: QdrantClient,
        *,
        collection: str,
        vector_size: int,
        distance: Distance,
    ) -> None:
        self._client = client
        self._collection = collection
        self._vector_size = vector_size
        self._distance = distance

    @property
    def collection(self) -> str:
        return self._collection

    @property
    def client(self) -> QdrantClient:
        return self._client

    def ensure_collection(self) -> None:
        """Create the collection when missing. Safe to call on every startup."""
        if self._client.collection_exists(self._collection):
            logger.debug("qdrant collection %s already exists", self._collection)
            return

        logger.info(
            "creating qdrant collection %s size=%d distance=%s",
            self._collection,
            self._vector_size,
            self._distance,
        )
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=VectorParams(size=self._vector_size, distance=self._distance),
        )

    def upsert(self, points: Sequence[PointStruct]) -> None:
        if not points:
            logger.debug("upsert called with no points")
            return

        # wait=True so the caller only records point uids that Qdrant has
        # durably accepted — otherwise Postgres could claim an index that does
        # not exist.
        with log_duration(logger, "qdrant upsert", collection=self._collection, points=len(points)):
            self._client.upsert(collection_name=self._collection, points=list(points), wait=True)

    def search(self, vector: Sequence[float], *, limit: int = 5) -> list[dict[str, Any]]:
        """Nearest points to a query vector, payload included.

        Returns plain dicts rather than Qdrant models so callers (and prompts)
        do not depend on the client library's types.
        """
        with log_duration(logger, "qdrant search", collection=self._collection, limit=limit):
            response = self._client.query_points(
                collection_name=self._collection,
                query=list(vector),
                limit=limit,
                with_payload=True,
            )
        return [{"score": point.score, **(point.payload or {})} for point in response.points]

    def delete(self, point_uids: Sequence[uuid.UUID]) -> None:
        if not point_uids:
            return

        with log_duration(
            logger, "qdrant delete", collection=self._collection, points=len(point_uids)
        ):
            self._client.delete(
                collection_name=self._collection,
                points_selector=[str(point_uid) for point_uid in point_uids],
                wait=True,
            )


@lru_cache(maxsize=1)
def _get_client() -> QdrantClient:
    config = get_config().qdrant
    logger.info("connecting to qdrant url=%s", config.url)
    return QdrantClient(
        url=config.url,
        api_key=config.api_key,
        timeout=config.timeout,
        prefer_grpc=config.prefer_grpc,
    )


@cache
def get_vector_store(collection: str, vector_size: int, distance: str | None = None) -> VectorStore:
    """Vector store for one collection, sharing the process-wide Qdrant client."""
    resolved = distance or get_config().qdrant.distance
    return VectorStore(
        _get_client(),
        collection=collection,
        vector_size=vector_size,
        distance=Distance(resolved),
    )
