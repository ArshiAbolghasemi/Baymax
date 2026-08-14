"""The knowledge base's vector store.

One place resolves "which collection, how wide" from config, so the API
startup, the indexing task and any future retrieval path all address the same
collection.
"""

from functools import lru_cache

from clients.vector_store import VectorStore, get_vector_store
from common.logging import get_logger
from config import get_config

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_store() -> VectorStore:
    config = get_config()
    logger.info(
        "initializing knowledge vector store collection=%s dimensions=%d distance=%s",
        config.knowledge_base.collection,
        config.embedding.dimensions,
        config.qdrant.distance,
    )
    return get_vector_store(
        collection=config.knowledge_base.collection,
        vector_size=config.embedding.dimensions,
        distance=config.qdrant.distance,
    )
