"""Instruction retrieval node.

The instruction collection holds curated guidance on *how* to answer — tone,
required caveats, escalation wording, house rules for a topic — as opposed to
the knowledge base, which holds *what* to answer. It is written outside this
service; hiro only reads it, and creates it if it does not exist yet so a fresh
deployment starts with an empty instruction set rather than an error.

Its content is operator-authored, never user-authored, which is why the prompt
may treat it as authoritative.
"""

import asyncio
from functools import lru_cache

from hiro.chat.agent.nodes.common import vector_search
from hiro.chat.agent.state import AgentState
from hiro.chat.tracing import trace
from hiro.clients.vector_store import VectorStore, get_vector_store
from hiro.common.logging import get_logger, log_duration
from hiro.config import get_config

logger = get_logger(__name__)


def _texts(hits: list[dict[str, object]], field: str) -> list[str]:
    """The payload field of each hit, blanks dropped."""
    values = [str(hit.get(field, "")).strip() for hit in hits]
    return [value for value in values if value]


@lru_cache(maxsize=1)
def get_instruction_store() -> VectorStore:
    config = get_config()
    logger.info(
        "initializing instruction vector store collection=%s dimensions=%d",
        config.chat.instruction_collection,
        config.embedding.dimensions,
    )
    store = get_vector_store(
        collection=config.chat.instruction_collection,
        vector_size=config.embedding.dimensions,
        distance=config.qdrant.distance,
    )
    store.ensure_collection()
    return store


@trace(
    "retrieve instructions",
    kind="retriever",
    input=lambda state: state["question"],
    output=lambda update: update["instructions"],
)
async def retrieve_instructions(state: AgentState) -> AgentState:
    """Retrieve the instructions that apply to this question."""
    config = get_config().chat
    question = state["question"]
    try:
        with log_duration(
            logger,
            "retrieve instructions",
            collection=config.instruction_collection,
            limit=config.instruction_top_k,
        ):
            hits = await asyncio.to_thread(
                vector_search, get_instruction_store(), question, config.instruction_top_k
            )
            found = _texts(hits, config.instruction_payload_field)
    except Exception:
        logger.exception("instruction retrieval failed, continuing without instructions")
        return {"instructions": []}

    field = config.instruction_payload_field
    instructions = found
    if hits and not instructions:
        logger.warning(
            "instruction points carry no %r payload field; set "
            "CHAT_INSTRUCTION_PAYLOAD_FIELD to the key this collection uses (keys=%s)",
            field,
            sorted(hits[0]),
        )
    logger.info("retrieved %d instruction(s)", len(instructions))
    return {"instructions": instructions}
