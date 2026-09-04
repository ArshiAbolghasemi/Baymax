"""Shared helpers for chat workflow nodes."""

from hiro.clients.embedding import get_embedding_client
from hiro.clients.vector_store import VectorStore


def render(template: str, setting: str, **values: object) -> str:
    """Format a configurable template, naming the setting if malformed."""
    try:
        return template.format(**values)
    except (KeyError, IndexError) as exc:
        msg = f"{setting} has an unknown placeholder {exc}; expected {sorted(values)}"
        raise ValueError(msg) from exc


def vector_search(store: VectorStore, question: str, limit: int) -> list[dict[str, object]]:
    """Embed a question and return the nearest points in one collection.

    Blocking: both clients are synchronous, so retrieval nodes call this
    through ``asyncio.to_thread``.
    """
    vector = get_embedding_client().embed([question])[0]
    return store.search(vector, limit=limit)
