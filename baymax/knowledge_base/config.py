"""Knowledge base domain configuration."""

import uuid

from dynaconf import Dynaconf

from baymax.common.env import dynaconf_kwargs

# Point uids are derived from the join row uid rather than random, so a retried
# indexing task rewrites the same point instead of orphaning the previous one.
DEFAULT_POINT_NAMESPACE = "6f8b6d1c-0d3a-4b2e-9b8a-1c2d3e4f5a6b"


class KnowledgeBaseConfig(Dynaconf):
    """Settings owned by the knowledge base itself.

    The collection name lives here, not in :class:`QdrantConfig` — Qdrant is
    shared infrastructure, the collection belongs to this domain.
    """

    def __init__(self) -> None:
        super().__init__(**dynaconf_kwargs())

    @property
    def collection(self) -> str:
        return str(self.get("KNOWLEDGE_BASE_COLLECTION", "baymax_v1"))

    @property
    def max_questions_per_entry(self) -> int:
        return int(self.get("KNOWLEDGE_BASE_MAX_QUESTIONS_PER_ENTRY", 256))

    @property
    def point_namespace(self) -> uuid.UUID:
        """Changing this re-points every future pair; existing points are unaffected."""
        return uuid.UUID(str(self.get("KNOWLEDGE_BASE_POINT_NAMESPACE", DEFAULT_POINT_NAMESPACE)))
