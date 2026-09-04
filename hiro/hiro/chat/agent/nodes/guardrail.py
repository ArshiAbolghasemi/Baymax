"""Medical-topic guardrail node."""

from hiro.chat import prompts
from hiro.chat.agent.models import get_guardrail_model
from hiro.chat.agent.state import AgentState
from hiro.common.logging import get_logger, log_duration
from hiro.config import get_config

logger = get_logger(__name__)

ALLOWED = "1"


async def guardrail(state: AgentState) -> AgentState:
    """Classify the question as medical (1) or not (0).

    Anything other than a leading 1 is treated as 0. A classifier that starts
    explaining itself, an endpoint that is down, or a prompt that cannot be
    fetched, cannot admit a non-medical question.
    """
    try:
        identifier = get_config().chat.prompt_guardrail
        messages = await prompts.get_messages(identifier, question=state["question"])
        with log_duration(logger, "guardrail"):
            reply = await get_guardrail_model().ainvoke(messages)
        verdict = str(reply.content).strip()[:1]
    except Exception:
        logger.exception("guardrail failed, blocking the question")
        return {"allowed": False}

    allowed = verdict == ALLOWED
    logger.info("guardrail verdict=%r allowed=%s", verdict, allowed)
    return {"allowed": allowed}
