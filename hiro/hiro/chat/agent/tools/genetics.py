"""MedlinePlus Genetics consumer genetics tool."""

import asyncio
import json
import xml.etree.ElementTree as ET
from typing import Any

from langchain_core.tools import tool

from hiro.chat.agent.tools.common import (
    ExternalServiceError,
    cached,
    clean_text,
    error_payload,
    get,
)
from hiro.chat.agent.tools.medlineplus import genetics_entity_type, parse_search_documents
from hiro.chat.agent.tools.schemas import GeneticsInput
from hiro.config import get_config


def _search_urls(xml_text: str, max_results: int) -> list[str]:
    root = ET.fromstring(xml_text)
    urls = []
    for result in root.findall(".//result")[:max_results]:
        url = (result.findtext("url") or "").strip()
        if url.startswith("https://medlineplus.gov/genetics/"):
            urls.append(url.rstrip("/"))
    return urls


def _api_url(page_url: str) -> str:
    path = page_url.removeprefix("https://medlineplus.gov/genetics/").strip("/")
    return f"https://medlineplus.gov/download/genetics/{path}.json"


def _nested_values(
    payload: dict[str, Any], list_key: str, item_key: str, value_key: str
) -> list[str]:
    values: list[str] = []
    for wrapper in payload.get(list_key, []):
        item = wrapper.get(item_key, {}) if isinstance(wrapper, dict) else {}
        value = item.get(value_key, "") if isinstance(item, dict) else ""
        if value:
            values.append(str(value))
    return values


def _detail(payload: dict[str, Any], page_url: str, max_summary_chars: int) -> dict[str, Any]:
    name = str(payload.get("gene-symbol") or payload.get("name") or page_url.rsplit("/", 1)[-1])
    text_parts: list[str] = []
    for wrapper in payload.get("text-list", []):
        text = wrapper.get("text", {}) if isinstance(wrapper, dict) else {}
        if isinstance(text, dict) and text.get("html"):
            text_parts.append(str(text["html"]))
    result: dict[str, Any] = {
        "name": name,
        "type": genetics_entity_type(page_url),
        "summary": clean_text(" ".join(text_parts), limit=max_summary_chars),
        "source": "MedlinePlus Genetics",
        "url": page_url,
    }
    related_genes = _nested_values(payload, "related-gene-list", "related-gene", "gene-symbol")
    related_conditions = _nested_values(
        payload, "related-health-condition-list", "related-health-condition", "name"
    )
    inheritance = _nested_values(payload, "inheritance-pattern-list", "inheritance-pattern", "memo")
    if related_genes:
        result["related_genes"] = related_genes[:10]
    if related_conditions:
        result["related_conditions"] = related_conditions[:10]
    if inheritance:
        result["inheritance"] = inheritance[:5]
    if payload.get("reviewed"):
        result["reviewed"] = payload["reviewed"]
    if payload.get("published"):
        result["published"] = payload["published"]
    return result


@tool(args_schema=GeneticsInput)
async def search_genetics(query: str) -> dict[str, Any]:
    """Search MedlinePlus Genetics for consumer-oriented genetics information.

    Use for genes and gene function, genetic conditions, inheritance, chromosomes,
    variants, and genetic mechanisms. Do not use for ordinary disease guidance or
    detailed official drug labels.
    """

    normalized_query = query.strip()

    async def fetch() -> dict[str, Any]:
        config = get_config().medical_tools
        try:
            response = await get(
                "search_genetics",
                config.medlineplus_search_url,
                params={
                    "db": "ghr",
                    "term": normalized_query,
                    "retmax": config.max_results,
                    "rettype": "brief",
                    "tool": "baymax",
                },
            )
            urls = _search_urls(response.text, config.max_results)
            results = parse_search_documents(
                response.text,
                max_results=config.max_results,
                max_summary_chars=config.max_summary_chars,
                genetics=True,
            )
            if urls:
                detail_responses = await asyncio.gather(
                    *(get("search_genetics", _api_url(page_url)) for page_url in urls),
                    return_exceptions=True,
                )
                results = []
                for page_url, detail_response in zip(urls, detail_responses, strict=True):
                    try:
                        payload = detail_response.json()  # type: ignore[union-attr]
                        results.append(_detail(payload, page_url, config.max_summary_chars))
                    except AttributeError, json.JSONDecodeError, TypeError:
                        continue
                if not results and detail_responses:
                    raise ExternalServiceError("MedlinePlus Genetics detail retrieval failed")
        except (ExternalServiceError, ET.ParseError) as exc:
            return error_payload(
                {"query": normalized_query, "results": []},
                "MedlinePlus Genetics",
                "https://medlineplus.gov/genetics/",
                exc,
            )
        return {
            "query": normalized_query,
            "status": "ok" if results else "no_results",
            "results": results,
            "source": "MedlinePlus Genetics",
            "url": "https://medlineplus.gov/genetics/",
        }

    return await cached(("genetics", normalized_query.casefold()), 900, fetch)
