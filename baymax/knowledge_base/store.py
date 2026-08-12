"""The knowledge base's vector store.

One place resolves "which collection, how wide" from config, so the API
startup, the indexing task and any future retrieval path all address the same
collection.
"""

from functools import lru_cache

from baymax.clients.vector_store import VectorStore, get_vector_store
from baymax.config import get_config


@lru_cache(maxsize=1)
def get_store() -> VectorStore:
    config = get_config()
    return get_vector_store(
        collection=config.knowledge_base.collection,
        vector_size=config.embedding.dimensions,
        distance=config.qdrant.distance,
    )
