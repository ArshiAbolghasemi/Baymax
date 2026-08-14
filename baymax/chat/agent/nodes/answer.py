"""Prompt construction and ReAct answer-model node."""

from langchain_core.messages import HumanMessage, SystemMessage

from baymax.chat.agent.models import get_answer_model, get_answer_tool_schemas
from baymax.chat.agent.nodes.common import render
from baymax.chat.agent.state import AgentState
from baymax.common.logging import get_logger, log_duration
from baymax.config import get_config

logger = get_logger(__name__)


def build_answer_messages(state: AgentState) -> list[SystemMessage | HumanMessage]:
    """Fold internal knowledge-base context and history into the prompt."""
    config = get_config().chat
    documents = state.get("documents") or []
    history = state.get("history") or []

    document_block = (
        "\n\n".join(f"[{index}] {text}" for index, text in enumerate(documents, start=1))
        if documents
        else config.no_documents_text
    )
    history_block = (
        "\n".join(f"- {text}" for text in history) if history else config.no_history_text
    )
    logger.debug(
        "answer prompt built question_chars=%d documents=%d document_chars=%d history=%d",
        len(state["question"]),
        len(documents),
        len(document_block),
        len(history),
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
    """Run one model step in the ReAct loop."""
    previous_messages = state.get("messages") or []
    messages = previous_messages or build_answer_messages(state)
    logger.info(
        "answer model step with %d document(s), %d earlier question(s), %d react message(s)",
        len(state.get("documents") or []),
        len(state.get("history") or []),
        len(previous_messages),
    )

    with log_duration(
        logger,
        "answer model invocation",
        react_messages=len(previous_messages),
        documents=len(state.get("documents") or []),
    ):
        llm_config = get_config().llm
        tools = get_answer_tool_schemas()
        logger.info(
            "answer request endpoint=%s model=%s tools=%d choice=auto",
            llm_config.base_url,
            llm_config.model,
            len(tools),
        )
        reply = await get_answer_model().ainvoke(
            messages,
            model=llm_config.model,
            tools=tools,
            tool_choice="auto",
        )
    tool_calls = getattr(reply, "tool_calls", None) or []
    logger.info(
        "answer model step completed tool_calls=%d content_chars=%d",
        len(tool_calls),
        len(str(reply.content)),
    )
    update: AgentState = {"messages": [*messages, reply] if not previous_messages else [reply]}
    if not tool_calls:
        update["answer"] = str(reply.content)
    return update
