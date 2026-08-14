"""Internal Qdrant knowledge-base retrieval node."""

import asyncio

from chat.agent.state import AgentState
from clients.embedding import get_embedding_client
from common.logging import get_logger, log_duration
from config import get_config
from knowledge_base.store import get_store

logger = get_logger(__name__)


def _search(question: str, top_k: int) -> list[dict[str, object]]:
    vector = get_embedding_client().embed([question])[0]
    return get_store().search(vector, limit=top_k)


async def retrieve_documents(state: AgentState) -> AgentState:
    """Retrieve top-k internal knowledge-base entries for the question."""
    config = get_config()
    question = state["question"]
    try:
        with log_duration(
            logger,
            "retrieve documents",
            question_chars=len(question),
            limit=config.chat.retrieval_top_k,
        ):
            hits = await asyncio.to_thread(_search, question, config.chat.retrieval_top_k)
    except Exception:
        logger.exception("document retrieval failed, continuing without context")
        return {"documents": []}
    documents = [str(hit.get("answer", "")).strip() for hit in hits]
    logger.info("retrieved %d document(s)", len(documents))
    return {"documents": [document for document in documents if document]}
