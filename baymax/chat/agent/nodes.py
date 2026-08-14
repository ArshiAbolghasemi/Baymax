"""The workflow's nodes.

Each is a plain async function taking the state and returning the keys it
changed, so any of them can be called directly in a test without a graph.
"""

import asyncio

from langchain_core.messages import HumanMessage, SystemMessage

from baymax.chat.agent.models import get_answer_model, get_guardrail_model
from baymax.chat.agent.state import AgentState
from baymax.chat.repository import list_recent_user_messages
from baymax.clients.embedding import get_embedding_client
from baymax.common.logging import get_logger, log_duration
from baymax.config import get_config
from baymax.db.session import async_session_scope
from baymax.knowledge_base.store import get_store

logger = get_logger(__name__)

ALLOWED = "1"


def render(template: str, setting: str, **values: object) -> str:
    """Format a configurable template, naming the setting if it is malformed.

    These come from the environment, so a typo'd placeholder is a configuration
    error and deserves to say which setting to fix.
    """
    try:
        return template.format(**values)
    except (KeyError, IndexError) as exc:
        msg = f"{setting} has an unknown placeholder {exc}; expected {sorted(values)}"
        raise ValueError(msg) from exc


async def guardrail(state: AgentState) -> AgentState:
    """Classify the question as medical (1) or not (0).

    Anything the model says other than a leading 1 is treated as 0. A classifier
    that starts explaining itself, or an endpoint that is down, must not become
    a way to get non-medical answers out of the assistant.
    """
    config = get_config().chat
    messages = [
        SystemMessage(content=config.guardrail_system_prompt),
        HumanMessage(
            content=render(
                config.guardrail_user_template,
                "CHAT_GUARDRAIL_USER_TEMPLATE",
                question=state["question"],
            )
        ),
    ]

    try:
        with log_duration(logger, "guardrail"):
            reply = await get_guardrail_model().ainvoke(messages)
        verdict = str(reply.content).strip()[:1]
    except Exception:
        logger.exception("guardrail failed, blocking the question")
        return {"allowed": False}

    allowed = verdict == ALLOWED
    logger.info("guardrail verdict=%r allowed=%s", verdict, allowed)
    return {"allowed": allowed}


async def blocked(_: AgentState) -> AgentState:
    """Refuse, with a fixed string rather than a generated one."""
    logger.info("question blocked by guardrail")
    return {"answer": get_config().chat.blocked_message}


async def retrieve_documents(state: AgentState) -> AgentState:
    """Top-k knowledge base entries for the question.

    The embedding and Qdrant clients are synchronous, so they run in a worker
    thread rather than blocking the event loop that is serving other sockets.
    """
    config = get_config()
    question = state["question"]

    def search() -> list[dict[str, object]]:
        vector = get_embedding_client().embed([question])[0]
        return get_store().search(vector, limit=config.chat.retrieval_top_k)

    try:
        with log_duration(logger, "retrieve documents"):
            hits = await asyncio.to_thread(search)
    except Exception:
        # Retrieval is an enhancement, not a precondition — answer without it.
        logger.exception("document retrieval failed, continuing without context")
        return {"documents": []}

    documents = [str(hit.get("answer", "")).strip() for hit in hits]
    logger.info("retrieved %d document(s)", len(documents))
    return {"documents": [d for d in documents if d]}


async def retrieve_history(state: AgentState) -> AgentState:
    """The user's previous questions in this session, oldest first."""
    config = get_config()

    try:
        async with async_session_scope() as session:
            rows = await list_recent_user_messages(
                session, state["session_uid"], limit=config.chat.history_turns
            )
    except Exception:
        logger.exception("history lookup failed, continuing without it")
        return {"history": []}

    history = [row.content for row in rows]
    logger.info("retrieved %d earlier question(s)", len(history))
    return {"history": history}


def build_answer_messages(state: AgentState) -> list[SystemMessage | HumanMessage]:
    """Fold the retrieved context into the prompt."""
    config = get_config().chat
    documents = state.get("documents") or []
    history = state.get("history") or []

    document_block = (
        "\n\n".join(f"[{i}] {text}" for i, text in enumerate(documents, start=1))
        if documents
        else config.no_documents_text
    )
    history_block = (
        "\n".join(f"- {text}" for text in history) if history else config.no_history_text
    )

    return [
        SystemMessage(
            content=render(
                config.answer_system_prompt,
                "CHAT_ANSWER_SYSTEM_PROMPT",
                system_prompt=config.system_prompt,
            )
        ),
        HumanMessage(
            content=render(
                config.answer_user_template,
                "CHAT_ANSWER_USER_TEMPLATE",
                documents=document_block,
                history=history_block,
                question=state["question"],
            )
        ),
    ]


async def answer(state: AgentState) -> AgentState:
    """Generate the reply.

    Tokens leave the graph through LangGraph's message stream as this runs; the
    returned text is the complete reply, which is what gets persisted.
    """
    messages = build_answer_messages(state)
    logger.info(
        "answering with %d document(s) and %d earlier question(s)",
        len(state.get("documents") or []),
        len(state.get("history") or []),
    )

    reply = await get_answer_model().ainvoke(messages)
    return {"answer": str(reply.content)}
