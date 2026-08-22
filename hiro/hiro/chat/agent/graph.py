"""The compiled workflow, and the streaming interface the chat service uses."""

import time
import uuid
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Literal

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from hiro.chat.agent import nodes
from hiro.chat.agent.state import AgentState
from hiro.chat.agent.tools import EXTERNAL_MEDICAL_TOOLS
from hiro.common.logging import get_logger

logger = get_logger(__name__)


def assistant_text(message: object) -> str:
    """Text the model generated, and nothing else.

    Two things are filtered out here, because both would otherwise reach the
    client as if the assistant had said them:

    * Non-assistant messages. The answer node returns its whole prompt into
      state on the first pass, so the system and user messages travel the same
      stream as the reply.
    * Non-text content blocks. Reasoning models return ``content`` as a list of
      blocks; ``str()`` on that dumps the model's private reasoning verbatim.
    """
    if not isinstance(message, AIMessage):
        return ""

    content = message.content
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


ANSWER_NODE = "answer"
BLOCKED_NODE = "blocked"
RETRIEVAL_NODES = [
    # "retrieve_documents",
    "retrieve_history"
]
TOOLS_NODE = "external_tools"


def route_after_guardrail(state: AgentState) -> Literal["blocked"] | list[str]:
    """Refuse, or fan out into both retrieval steps at once.

    Returning a list of node names is what makes LangGraph run them
    concurrently rather than one after the other.
    """
    if not state.get("allowed"):
        logger.info("agent routing branch=blocked")
        return BLOCKED_NODE
    logger.info("agent routing branch=retrieval nodes=%d", len(RETRIEVAL_NODES))
    return RETRIEVAL_NODES


def route_after_answer(state: AgentState) -> Literal["external_tools", "__end__"]:
    """Continue the ReAct loop exactly when the model requested a tool."""
    messages = state.get("messages") or []
    if messages and getattr(messages[-1], "tool_calls", None):
        tool_calls = messages[-1].tool_calls
        tool_names = [call.get("name", "unknown") for call in tool_calls]
        logger.info("agent routing branch=tools count=%d tools=%s", len(tool_calls), tool_names)
        return TOOLS_NODE
    logger.info("agent routing branch=complete")
    return END


@lru_cache(maxsize=1)
def get_graph():
    """Build and compile the workflow once per process."""
    builder = StateGraph(AgentState)

    builder.add_node("guardrail", nodes.guardrail)
    builder.add_node(BLOCKED_NODE, nodes.blocked)
    # builder.add_node("retrieve_documents", nodes.retrieve_documents)
    builder.add_node("retrieve_history", nodes.retrieve_history)
    builder.add_node(ANSWER_NODE, nodes.answer)
    builder.add_node(TOOLS_NODE, ToolNode(EXTERNAL_MEDICAL_TOOLS))

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

    builder.add_conditional_edges(ANSWER_NODE, route_after_answer, [TOOLS_NODE, END])
    builder.add_edge(TOOLS_NODE, ANSWER_NODE)
    builder.add_edge(BLOCKED_NODE, END)

    logger.info(
        "chat agent graph compiled retrieval_nodes=%d external_tools=%d",
        len(RETRIEVAL_NODES),
        len(EXTERNAL_MEDICAL_TOOLS),
    )
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
    started = time.perf_counter()
    chunks_yielded = 0
    chars_yielded = 0
    logger.info("agent run started session_uid=%s question_chars=%d", session_uid, len(question))

    try:
        async for mode, chunk in get_graph().astream(state, stream_mode=["updates", "messages"]):
            if mode == "messages":
                message, metadata = chunk
                if metadata.get("langgraph_node") != ANSWER_NODE:
                    continue
                rendered = assistant_text(message)
                if rendered:
                    chunks_yielded += 1
                    chars_yielded += len(rendered)
                    yield rendered

            elif mode == "updates" and BLOCKED_NODE in chunk:
                rendered = chunk[BLOCKED_NODE]["answer"]
                chunks_yielded += 1
                chars_yielded += len(rendered)
                yield rendered
    except Exception:
        logger.exception(
            "agent run failed session_uid=%s chunks=%d chars=%d",
            session_uid,
            chunks_yielded,
            chars_yielded,
        )
        raise
    finally:
        elapsed = (time.perf_counter() - started) * 1_000
        logger.info(
            "agent run finished session_uid=%s chunks=%d chars=%d elapsed_ms=%.1f",
            session_uid,
            chunks_yielded,
            chars_yielded,
            elapsed,
        )
