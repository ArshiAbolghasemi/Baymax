"""DailyMed current Structured Product Label tool."""

import json
import xml.etree.ElementTree as ET
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any

from langchain_core.tools import tool

from hiro.chat.agent.tools.common import (
    ExternalServiceError,
    cached,
    clean_text,
    element_text,
    error_payload,
    get,
)
from hiro.chat.agent.tools.schemas import DrugLabelInput, DrugLabelSection
from hiro.config import get_config

_SECTION_TERMS: dict[str, tuple[str, ...]] = {
    "indications": ("indications and usage", "indications"),
    "dosage": ("dosage and administration", "dosage"),
    "contraindications": ("contraindications",),
    "warnings": ("warnings and precautions", "boxed warning", "warnings"),
    "adverse_reactions": ("adverse reactions",),
    "drug_interactions": ("drug interactions", "interactions"),
    "pregnancy": ("pregnancy", "use in specific populations"),
    "clinical_pharmacology": ("clinical pharmacology",),
}


def _section_title(section: ET.Element) -> str:
    for child in section:
        if child.tag.rsplit("}", 1)[-1] == "title":
            return element_text(child, limit=200)
    return element_text(section.find("./{*}title"), limit=200)


def _extract_sections(root: ET.Element, max_chars: int) -> dict[str, str]:
    found: dict[str, list[str]] = {name: [] for name in _SECTION_TERMS}
    for section in root.findall(".//{*}section"):
        lowered = _section_title(section).casefold()
        if not lowered:
            continue
        for name, terms in _SECTION_TERMS.items():
            if any(term in lowered for term in terms):
                text_nodes = section.findall("./{*}text")
                content = " ".join(element_text(node, limit=20_000) for node in text_nodes)
                content = clean_text(content, limit=max_chars)
                if content and content not in found[name]:
                    found[name].append(content)
    return {name: "\n\n".join(parts) for name, parts in found.items() if parts}


def _descendant_text(root: ET.Element, parent_name: str, child_name: str) -> str:
    for parent in root.iter():
        if parent.tag.rsplit("}", 1)[-1] != parent_name:
            continue
        for child in parent.iter():
            if child.tag.rsplit("}", 1)[-1] == child_name:
                text = element_text(child, limit=300)
                if text:
                    return text
    return ""


def _local_attribute(root: ET.Element, name: str, attribute: str) -> str:
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == name and element.attrib.get(attribute):
            return element.attrib[attribute]
    return ""


def _published_timestamp(value: str) -> float:
    try:
        return parsedate_to_datetime(value).replace(tzinfo=UTC).timestamp()
    except TypeError, ValueError, OverflowError:
        return 0.0


def _best_label(labels: list[dict[str, Any]], drug_name: str) -> dict[str, Any] | None:
    if not labels:
        return None
    needle = drug_name.casefold()

    def score(label: dict[str, Any]) -> tuple[int, float, int]:
        title = str(label.get("title", "")).casefold()
        exactish = int(title.startswith(needle + " ") or title.startswith(needle + "-"))
        try:
            version = int(label.get("spl_version", 0) or 0)
        except TypeError, ValueError:
            version = 0
        return exactish, _published_timestamp(str(label.get("published_date", ""))), version

    return max(labels, key=score)


@tool(args_schema=DrugLabelInput)
async def search_drug_label(drug_name: str, section: DrugLabelSection = "all") -> dict[str, Any]:
    """Retrieve current official US prescribing-label content from DailyMed.

    Use for labeled indications, dosage, contraindications, warnings, adverse
    reactions, drug interactions, pregnancy, or clinical pharmacology. This is
    official labeling, not a source for FAERS safety-signal/report questions.
    """

    normalized_name = drug_name.strip()

    async def fetch() -> dict[str, Any]:
        config = get_config().medical_tools
        identity = {"drug": normalized_name, "section": section, "content": ""}
        try:
            search_response = await get(
                "search_drug_label",
                f"{config.dailymed_api_url}/spls.json",
                params={
                    "drug_name": normalized_name,
                    "name_type": "both",
                    "pagesize": 20,
                    "page": 1,
                },
            )
            labels = search_response.json().get("data", [])
            label = _best_label(labels, normalized_name)
            if label is None:
                return {
                    **identity,
                    "status": "no_results",
                    "source": "DailyMed",
                    "url": "https://dailymed.nlm.nih.gov/dailymed/",
                }

            setid = str(label["setid"])
            xml_response = await get(
                "search_drug_label", f"{config.dailymed_api_url}/spls/{setid}.xml"
            )
            root = ET.fromstring(xml_response.text)
            sections = _extract_sections(root, config.max_label_section_chars)
            content: str | dict[str, str]
            content = (
                {
                    name: clean_text(text, limit=min(config.max_label_section_chars, 1_000))
                    for name, text in sections.items()
                }
                if section == "all"
                else sections.get(section, "")
            )
            url = f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"
            result: dict[str, Any] = {
                **identity,
                "status": "ok" if content else "no_results",
                "content": content,
                "setid": setid,
                "source": "DailyMed",
                "url": url,
                "label_title": label.get("title", ""),
                "label_metadata": {
                    "published_date": label.get("published_date"),
                    "spl_version": label.get("spl_version"),
                    "document_id": _local_attribute(root, "id", "root"),
                    "effective_time": _local_attribute(root, "effectiveTime", "value"),
                },
            }
            generic_name = _descendant_text(root, "genericMedicine", "name")
            brand_name = _descendant_text(root, "manufacturedProduct", "name")
            if generic_name:
                result["generic_name"] = generic_name
            if brand_name:
                result["brand_name"] = brand_name
            return result
        except (
            AttributeError,
            ExternalServiceError,
            ET.ParseError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            return error_payload(
                identity, "DailyMed", "https://dailymed.nlm.nih.gov/dailymed/", exc
            )

    return await cached(("label", normalized_name.casefold(), section), 300, fetch)
