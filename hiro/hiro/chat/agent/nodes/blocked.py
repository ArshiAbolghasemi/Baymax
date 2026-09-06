"""Fixed refusal node for questions rejected by the guardrail."""

from hiro.chat import prompts
from hiro.chat.agent.state import AgentState
from hiro.chat.tracing import trace
from hiro.common.logging import get_logger
from hiro.config import get_config

logger = get_logger(__name__)


@trace(
    "blocked refusal",
    input=lambda state: state["question"],
    output=lambda update: update["answer"],
)
async def blocked(_: AgentState) -> AgentState:
    """Refuse with a fixed string rather than generated content."""
    logger.info("question blocked by guardrail")
    return {"answer": await prompts.get_text(get_config().chat.prompt_blocked)}
