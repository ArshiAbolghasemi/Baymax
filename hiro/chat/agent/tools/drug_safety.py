"""openFDA/FAERS adverse-event aggregation tool."""

import asyncio
import json
from typing import Any

from langchain_core.tools import tool

from chat.agent.tools.common import ExternalServiceError, cached, error_payload, get
from chat.agent.tools.schemas import DrugSafetyInput
from config import get_config

SOURCE = "openFDA / FAERS"
SOURCE_URL = "https://open.fda.gov/apis/drug/event/"


def _search_term(drug_name: str) -> str:
    escaped = drug_name.replace("\\", "\\\\").replace('"', '\\"')
    return (
        f'(patient.drug.medicinalproduct:"{escaped}" OR '
        f'patient.drug.openfda.brand_name:"{escaped}" OR '
        f'patient.drug.openfda.generic_name:"{escaped}")'
    )


def _report_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    results = payload.get("results", [])
    if not results:
        return None
    report = results[0]
    summary: dict[str, Any] = {
        "safety_report_id": report.get("safetyreportid"),
        "receipt_date": report.get("receiptdate"),
        "serious": report.get("serious") == "1",
    }
    seriousness = [
        key.removeprefix("seriousness")
        for key, value in report.items()
        if key.startswith("seriousness") and value == "1"
    ]
    if seriousness:
        summary["seriousness_categories"] = seriousness
    return {key: value for key, value in summary.items() if value is not None}


def _with_disclaimer(payload: dict[str, Any]) -> dict[str, Any]:
    payload["disclaimer"] = get_config().medical_tools.faers_disclaimer
    return payload


@tool(args_schema=DrugSafetyInput)
async def search_drug_safety(drug_name: str, limit: int = 10) -> dict[str, Any]:
    """Summarize reported adverse events and safety reports from openFDA/FAERS.

    Use for reported adverse events, FAERS reports, safety signals, or recent
    drug-safety reports. Counts are spontaneous reports and must never be treated
    as incidence, probability, or proof that the drug caused an event.
    """

    normalized_name = drug_name.strip()

    async def fetch() -> dict[str, Any]:
        config = get_config().medical_tools
        search = _search_term(normalized_name)
        identity = {"drug": normalized_name, "reported_events": []}
        try:
            reaction_response = await get(
                "search_drug_safety",
                config.openfda_event_url,
                params={
                    "search": search,
                    "count": "patient.reaction.reactionmeddrapt.exact",
                    "limit": limit,
                },
            )
            reaction_payload = reaction_response.json()
        except ExternalServiceError as exc:
            if exc.status_code == 404:
                return _with_disclaimer(
                    {
                        **identity,
                        "status": "no_results",
                        "source": SOURCE,
                        "url": SOURCE_URL,
                    }
                )
            return _with_disclaimer(error_payload(identity, SOURCE, SOURCE_URL, exc))
        except json.JSONDecodeError as exc:
            return _with_disclaimer(error_payload(identity, SOURCE, SOURCE_URL, exc))

        try:
            events = [
                {"reaction": item.get("term", ""), "count": int(item.get("count", 0))}
                for item in reaction_payload.get("results", [])[:limit]
                if item.get("term")
            ]
        except (AttributeError, TypeError, ValueError) as exc:
            return _with_disclaimer(error_payload(identity, SOURCE, SOURCE_URL, exc))
        if not events:
            return _with_disclaimer(
                {
                    **identity,
                    "status": "no_results",
                    "source": SOURCE,
                    "url": SOURCE_URL,
                }
            )

        auxiliary = await asyncio.gather(
            get(
                "search_drug_safety",
                config.openfda_event_url,
                params={"search": search, "count": "serious", "limit": 10},
            ),
            get(
                "search_drug_safety",
                config.openfda_event_url,
                params={"search": search, "sort": "receiptdate:asc", "limit": 1},
            ),
            get(
                "search_drug_safety",
                config.openfda_event_url,
                params={"search": search, "sort": "receiptdate:desc", "limit": 1},
            ),
            return_exceptions=True,
        )

        result: dict[str, Any] = {
            "drug": normalized_name,
            "status": "ok",
            "reported_events": events,
            "source": SOURCE,
            "url": SOURCE_URL,
        }
        try:
            seriousness_payload = auxiliary[0].json()  # type: ignore[union-attr]
            result["seriousness_counts"] = [
                {"serious": str(item.get("term")) == "1", "count": int(item.get("count", 0))}
                for item in seriousness_payload.get("results", [])
            ]
        except AttributeError, json.JSONDecodeError, TypeError, ValueError:
            pass

        endpoint_reports: list[dict[str, Any]] = []
        for response in auxiliary[1:]:
            try:
                summary = _report_summary(response.json())  # type: ignore[union-attr]
            except AttributeError, json.JSONDecodeError, TypeError:
                summary = None
            if summary:
                endpoint_reports.append(summary)
        if endpoint_reports:
            dates = [r["receipt_date"] for r in endpoint_reports if r.get("receipt_date")]
            if dates:
                result["report_date_range"] = {"from": min(dates), "to": max(dates)}
            result["boundary_reports"] = endpoint_reports

        metadata = reaction_payload.get("meta", {})
        if metadata.get("last_updated"):
            result["data_last_updated"] = metadata["last_updated"]
        return _with_disclaimer(result)

    return await cached(("safety", normalized_name.casefold(), limit), 120, fetch)
