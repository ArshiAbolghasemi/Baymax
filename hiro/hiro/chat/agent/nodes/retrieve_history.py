"""Conversation-history retrieval node."""

from hiro.chat.agent.state import AgentState
from hiro.chat.repository import list_recent_user_messages
from hiro.chat.tracing import trace
from hiro.common.logging import get_logger, log_duration
from hiro.config import get_config
from hiro.db.session import async_session_scope

logger = get_logger(__name__)


@trace(
    "retrieve history",
    kind="retriever",
    input=lambda state: state["question"],
    output=lambda update: update["history"],
)
async def retrieve_history(state: AgentState) -> AgentState:
    """Retrieve the user's earlier questions in this session, oldest first."""
    config = get_config()

    try:
        with log_duration(
            logger,
            "retrieve history",
            session_uid=state["session_uid"],
            limit=config.chat.history_turns,
        ):
            async with async_session_scope() as session:
                rows = await list_recent_user_messages(
                    session, state["session_uid"], limit=config.chat.history_turns
                )
            history = [row.content for row in rows]
    except Exception:
        logger.exception("history lookup failed, continuing without it")
        return {"history": []}

    logger.info("retrieved %d earlier question(s)", len(history))
    return {"history": history}
