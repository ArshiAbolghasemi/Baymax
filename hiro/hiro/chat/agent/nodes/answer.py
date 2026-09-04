"""Prompt construction and ReAct answer-model node."""

from langchain_core.messages import BaseMessage

from hiro.chat import prompts
from hiro.chat.agent.models import get_answer_model, get_answer_tool_schemas
from hiro.chat.agent.state import AgentState
from hiro.common.logging import get_logger, log_duration
from hiro.config import get_config

logger = get_logger(__name__)


async def build_answer_messages(state: AgentState) -> list[BaseMessage]:
    """Fold instructions, internal knowledge-base context and history into the prompt.

    The blocks are assembled here; the prompt they are substituted into — and
    the stand-in text for an empty one — comes from Phoenix.
    """
    config = get_config().chat
    instructions = state.get("instructions") or []
    documents = state.get("documents") or []
    history = state.get("history") or []

    instruction_block = (
        "\n".join(f"- {text}" for text in instructions)
        if instructions
        else await prompts.get_text(config.prompt_no_instructions)
    )
    document_block = (
        "\n\n".join(f"[{index}] {text}" for index, text in enumerate(documents, start=1))
        if documents
        else await prompts.get_text(config.prompt_no_documents)
    )
    history_block = (
        "\n".join(f"- {text}" for text in history)
        if history
        else await prompts.get_text(config.prompt_no_history)
    )
    logger.debug(
        "answer prompt built question_chars=%d instructions=%d documents=%d "
        "document_chars=%d history=%d",
        len(state["question"]),
        len(instructions),
        len(documents),
        len(document_block),
        len(history),
    )

    return await prompts.get_messages(
        config.prompt_answer,
        instructions=instruction_block,
        documents=document_block,
        history=history_block,
        question=state["question"],
    )


async def answer(state: AgentState) -> AgentState:
    """Run one model step in the ReAct loop."""
    previous_messages = state.get("messages") or []
    messages = previous_messages or await build_answer_messages(state)
    logger.info(
        "answer model step with %d instruction(s), %d document(s), %d earlier question(s), "
        "%d react message(s)",
        len(state.get("instructions") or []),
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
        chatbot_config = get_config().chatbot
        tools = await get_answer_tool_schemas()
        logger.info(
            "answer request endpoint=%s model=%s tools=%d choice=auto",
            chatbot_config.base_url,
            chatbot_config.model,
            len(tools),
        )
        reply = await get_answer_model().ainvoke(
            messages,
            model=chatbot_config.model,
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
