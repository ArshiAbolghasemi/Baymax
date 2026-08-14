"""External authoritative medical tools exposed to the ReAct agent."""

from langchain_core.tools import BaseTool

from chat.agent.tools.common import clear_tool_cache
from chat.agent.tools.drug_label import search_drug_label
from chat.agent.tools.drug_safety import search_drug_safety
from chat.agent.tools.genetics import search_genetics
from chat.agent.tools.health_info import search_health_info

EXTERNAL_MEDICAL_TOOLS: list[BaseTool] = [
    search_health_info,
    search_drug_label,
    search_drug_safety,
    search_genetics,
]

__all__ = [
    "EXTERNAL_MEDICAL_TOOLS",
    "clear_tool_cache",
    "search_drug_label",
    "search_drug_safety",
    "search_genetics",
    "search_health_info",
]
