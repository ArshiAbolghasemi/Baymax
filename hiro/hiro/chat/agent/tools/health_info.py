"""MedlinePlus patient-friendly health-topic tool."""

import xml.etree.ElementTree as ET
from typing import Any

from langchain_core.tools import tool

from hiro.chat.agent.tools.common import ExternalServiceError, cached, error_payload, get
from hiro.chat.agent.tools.medlineplus import parse_search_documents
from hiro.chat.agent.tools.schemas import SearchInput
from hiro.config import get_config


@tool(args_schema=SearchInput)
async def search_health_info(query: str) -> dict[str, Any]:
    """Search MedlinePlus for patient-friendly disease and condition information.

    Use for symptoms, causes, diagnosis, treatment, prevention, and general disease
    information. Do not use for detailed official drug labels or genetics questions;
    use search_drug_label or search_genetics for those.
    """

    normalized_query = query.strip()

    async def fetch() -> dict[str, Any]:
        config = get_config().medical_tools
        try:
            response = await get(
                "search_health_info",
                config.medlineplus_search_url,
                params={
                    "db": "healthTopics",
                    "term": normalized_query,
                    "retmax": config.max_results,
                    "rettype": "brief",
                    "tool": "baymax",
                },
            )
            results = parse_search_documents(
                response.text,
                max_results=config.max_results,
                max_summary_chars=config.max_summary_chars,
            )
        except (ExternalServiceError, ET.ParseError) as exc:
            return error_payload(
                {"query": normalized_query, "results": []},
                "MedlinePlus",
                "https://medlineplus.gov/healthtopics.html",
                exc,
            )
        return {
            "query": normalized_query,
            "status": "ok" if results else "no_results",
            "results": results,
            "source": "MedlinePlus",
            "url": "https://medlineplus.gov/healthtopics.html",
        }

    return await cached(("health", normalized_query.casefold()), 900, fetch)
