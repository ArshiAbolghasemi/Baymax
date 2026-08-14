"""Fixed refusal node for questions rejected by the guardrail."""

from baymax.chat.agent.state import AgentState
from baymax.common.logging import get_logger
from baymax.config import get_config

logger = get_logger(__name__)


async def blocked(_: AgentState) -> AgentState:
    """Refuse with a fixed string rather than generated content."""
    logger.info("question blocked by guardrail")
    return {"answer": get_config().chat.blocked_message}
