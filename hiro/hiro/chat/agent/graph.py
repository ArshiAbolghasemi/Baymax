"""The compiled workflow, and the streaming interface the chat service uses."""

import time
import uuid
from collections.abc import AsyncIterator
from typing import Literal

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from hiro.chat.agent import nodes
from hiro.chat.agent.events import AgentEvent, TextDelta, ToolCall, ToolResult
from hiro.chat.agent.mcp import get_mcp_tools
from hiro.chat.agent.state import AgentState
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
    "retrieve_documents",
    "retrieve_instructions",
    "retrieve_history",
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


_graph = None


async def get_graph():
    """Build and compile the workflow once per process.

    Asynchronous because the tool node is wired from the tools the MCP server
    advertises, which are discovered over the network on first use.
    """
    global _graph
    if _graph is not None:
        return _graph

    tools = await get_mcp_tools()
    builder = StateGraph(AgentState)

    builder.add_node("guardrail", nodes.guardrail)
    builder.add_node(BLOCKED_NODE, nodes.blocked)
    # builder.add_node("retrieve_documents", nodes.retrieve_documents)
    builder.add_node("retrieve_instructions", nodes.retrieve_instructions)
    builder.add_node("retrieve_history", nodes.retrieve_history)
    builder.add_node(ANSWER_NODE, nodes.answer)
    builder.add_node(TOOLS_NODE, ToolNode(tools))

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
        len(tools),
    )
    _graph = builder.compile()
    return _graph


def _tool_calls(update: dict) -> list[ToolCall]:
    """Tool calls the answer node just requested, if any."""
    messages = update.get("messages") or []
    calls = getattr(messages[-1], "tool_calls", None) if messages else None
    return [
        ToolCall(
            id=str(call.get("id") or ""),
            name=str(call.get("name") or "unknown"),
            arguments=dict(call.get("args") or {}),
        )
        for call in (calls or [])
    ]


def _tool_results(update: dict) -> list[ToolResult]:
    """What the tools node returned, one event per tool message."""
    return [
        ToolResult(
            tool_call_id=str(getattr(message, "tool_call_id", "") or ""),
            name=str(getattr(message, "name", "") or "unknown"),
            content=str(getattr(message, "content", "") or ""),
        )
        for message in (update.get("messages") or [])
    ]


async def stream_answer(question: str, session_uid: uuid.UUID) -> AsyncIterator[AgentEvent]:
    """Run the workflow, yielding what it does as it does it.

    Two stream modes are consumed at once:

    * ``messages`` carries LLM tokens. They are filtered to the answer node, so
      the guardrail's single character never reaches the user.
    * ``updates`` carries node results: the blocked branch's fixed refusal —
      which calls no model and therefore emits no tokens — plus the tool calls
      the answer node requested and the results the tools node produced.
    """
    state: AgentState = {"question": question, "session_uid": session_uid}
    started = time.perf_counter()
    chunks_yielded = 0
    chars_yielded = 0
    tools_called = 0
    logger.info("agent run started session_uid=%s question_chars=%d", session_uid, len(question))

    try:
        graph = await get_graph()
        async for mode, chunk in graph.astream(state, stream_mode=["updates", "messages"]):
            if mode == "messages":
                message, metadata = chunk
                if metadata.get("langgraph_node") != ANSWER_NODE:
                    continue
                rendered = assistant_text(message)
                if rendered:
                    chunks_yielded += 1
                    chars_yielded += len(rendered)
                    yield TextDelta(rendered)

            elif mode == "updates":
                if BLOCKED_NODE in chunk:
                    rendered = chunk[BLOCKED_NODE]["answer"]
                    chunks_yielded += 1
                    chars_yielded += len(rendered)
                    yield TextDelta(rendered)
                elif ANSWER_NODE in chunk:
                    for call in _tool_calls(chunk[ANSWER_NODE]):
                        tools_called += 1
                        yield call
                elif TOOLS_NODE in chunk:
                    for result in _tool_results(chunk[TOOLS_NODE]):
                        yield result
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
            "agent run finished session_uid=%s chunks=%d chars=%d tool_calls=%d elapsed_ms=%.1f",
            session_uid,
            chunks_yielded,
            chars_yielded,
            tools_called,
            elapsed,
        )
