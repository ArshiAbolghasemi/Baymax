"""Internal Qdrant knowledge-base retrieval node."""

import asyncio

from hiro.chat.agent.nodes.common import vector_search
from hiro.chat.agent.state import AgentState
from hiro.chat.tracing import trace
from hiro.common.logging import get_logger, log_duration
from hiro.config import get_config
from hiro.knowledge_base.store import get_store

logger = get_logger(__name__)


@trace(
    "retrieve knowledge base",
    kind="retriever",
    input=lambda state: state["question"],
    output=lambda update: update["documents"],
)
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
            hits = await asyncio.to_thread(
                vector_search, get_store(), question, config.chat.retrieval_top_k
            )
            documents = [text for hit in hits if (text := str(hit.get("answer", "")).strip())]
    except Exception:
        logger.exception("document retrieval failed, continuing without context")
        return {"documents": []}
    logger.info("retrieved %d document(s)", len(documents))
    return {"documents": documents}
