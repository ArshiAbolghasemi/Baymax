"""Medical-topic guardrail node."""

from langchain_core.messages import HumanMessage, SystemMessage

from chat.agent.models import get_guardrail_model
from chat.agent.nodes.common import render
from chat.agent.state import AgentState
from common.logging import get_logger, log_duration
from config import get_config

logger = get_logger(__name__)

ALLOWED = "1"


async def guardrail(state: AgentState) -> AgentState:
    """Classify the question as medical (1) or not (0).

    Anything other than a leading 1 is treated as 0. A classifier that starts
    explaining itself, or an endpoint that is down, cannot admit a non-medical
    question.
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
