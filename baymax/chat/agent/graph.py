"""The compiled workflow, and the streaming interface the chat service uses."""

import uuid
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Literal

from langgraph.graph import END, START, StateGraph

from baymax.chat.agent import nodes
from baymax.chat.agent.state import AgentState
from baymax.common.logging import get_logger

logger = get_logger(__name__)

ANSWER_NODE = "answer"
BLOCKED_NODE = "blocked"
RETRIEVAL_NODES = ["retrieve_documents", "retrieve_history"]


def route_after_guardrail(state: AgentState) -> Literal["blocked"] | list[str]:
    """Refuse, or fan out into both retrieval steps at once.

    Returning a list of node names is what makes LangGraph run them
    concurrently rather than one after the other.
    """
    if not state.get("allowed"):
        return BLOCKED_NODE
    return RETRIEVAL_NODES


@lru_cache(maxsize=1)
def get_graph():
    """Build and compile the workflow once per process."""
    builder = StateGraph(AgentState)

    builder.add_node("guardrail", nodes.guardrail)
    builder.add_node(BLOCKED_NODE, nodes.blocked)
    builder.add_node("retrieve_documents", nodes.retrieve_documents)
    builder.add_node("retrieve_history", nodes.retrieve_history)
    builder.add_node(ANSWER_NODE, nodes.answer)

    builder.add_edge(START, "guardrail")
    builder.add_conditional_edges(
        "guardrail",
        route_after_guardrail,
        [BLOCKED_NODE, *RETRIEVAL_NODES],
    )

    # Both retrieval nodes lead to answer; LangGraph waits for both before
    # running it, which is exactly the join we want.
    for node in RETRIEVAL_NODES:
        builder.add_edge(node, ANSWER_NODE)

    builder.add_edge(ANSWER_NODE, END)
    builder.add_edge(BLOCKED_NODE, END)

    logger.info("chat agent graph compiled")
    return builder.compile()


async def stream_answer(question: str, session_uid: uuid.UUID) -> AsyncIterator[str]:
    """Run the workflow, yielding the reply in chunks.

    Two stream modes are consumed at once:

    * ``messages`` carries LLM tokens. They are filtered to the answer node, so
      the guardrail's single character never reaches the user.
    * ``updates`` carries node results, which is how the blocked branch — which
      calls no model and therefore emits no tokens — delivers its fixed refusal.
    """
    state: AgentState = {"question": question, "session_uid": session_uid}

    async for mode, chunk in get_graph().astream(state, stream_mode=["updates", "messages"]):
        if mode == "messages":
            message, metadata = chunk
            if metadata.get("langgraph_node") != ANSWER_NODE:
                continue
            text = getattr(message, "content", "")
            if text:
                yield str(text)

        elif mode == "updates" and BLOCKED_NODE in chunk:
            yield chunk[BLOCKED_NODE]["answer"]
