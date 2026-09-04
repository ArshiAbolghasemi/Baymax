"""Shared helpers for chat workflow nodes."""

from hiro.clients.embedding import get_embedding_client
from hiro.clients.vector_store import VectorStore


def vector_search(store: VectorStore, question: str, limit: int) -> list[dict[str, object]]:
    """Embed a question and return the nearest points in one collection.

    Blocking: both clients are synchronous, so retrieval nodes call this
    through ``asyncio.to_thread``.
    """
    vector = get_embedding_client().embed([question])[0]
    return store.search(vector, limit=limit)
