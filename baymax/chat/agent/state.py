"""State passed between the graph's nodes."""

import uuid
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """What the workflow knows as it runs.

    ``documents`` and ``history`` are written by different nodes running in
    parallel. They are separate keys on purpose: LangGraph only needs a reducer
    when two concurrent nodes write the *same* key.
    """

    # Inputs
    session_uid: uuid.UUID
    question: str

    # guardrail
    allowed: bool

    # retrieval, filled concurrently
    documents: list[str]
    history: list[str]

    # ReAct conversation. ``add_messages`` appends model/tool turns while the
    # answer and external-tools nodes loop.
    messages: Annotated[list[AnyMessage], add_messages]

    # answer / blocked
    answer: str
