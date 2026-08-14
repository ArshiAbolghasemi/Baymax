"""Parsing helpers for MedlinePlus search responses."""

import xml.etree.ElementTree as ET
from typing import Any

from chat.agent.tools.common import element_text


def parse_search_documents(
    xml_text: str, *, max_results: int, max_summary_chars: int, genetics: bool = False
) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    results: list[dict[str, Any]] = []
    for document in root.findall(".//document")[:max_results]:
        fields: dict[str, list[str]] = {}
        for content in document.findall("./content"):
            name = content.attrib.get("name", "").lower()
            fields.setdefault(name, []).append(element_text(content, limit=max_summary_chars))

        title = next(iter(fields.get("title", [])), "").strip()
        summary = next(iter(fields.get("fullsummary", []) or fields.get("snippet", [])), "").strip()
        url = document.attrib.get("url", "")
        if not title and not url:
            continue

        if genetics:
            entity_type = genetics_entity_type(url)
            result: dict[str, Any] = {
                "name": title,
                "type": entity_type,
                "summary": summary,
                "source": "MedlinePlus Genetics",
                "url": url,
            }
            related_genes = fields.get("gene", []) + fields.get("genes", [])
            related_conditions = fields.get("condition", []) + fields.get("conditions", [])
            if related_genes:
                result["related_genes"] = related_genes[:10]
            if related_conditions:
                result["related_conditions"] = related_conditions[:10]
            results.append(result)
        else:
            results.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": url,
                    "source": "MedlinePlus",
                }
            )
    return results


def genetics_entity_type(url: str) -> str:
    lowered_url = url.lower()
    return next(
        (
            kind
            for marker, kind in (
                ("/gene/", "gene"),
                ("/condition/", "condition"),
                ("/chromosome/", "chromosome"),
                ("/mitochondrial-dna/", "mitochondrial_dna"),
                ("/understanding/", "genetics_topic"),
            )
            if marker in lowered_url
        ),
        "genetics_topic",
    )
