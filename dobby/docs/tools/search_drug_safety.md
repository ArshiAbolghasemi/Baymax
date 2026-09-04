# `search_drug_safety`

Summarizes adverse-event reports associated with a drug in openFDA's FDA
Adverse Event Reporting System (FAERS) data.

## Critical interpretation

FAERS contains spontaneous reports. A report does not prove that the drug
caused the event, and report counts are not incidence rates, probabilities, or
a comparison of risk between drugs. Duplicate reports, stimulated reporting,
missing data, and reporting bias can affect the results. The response always
includes the configured disclaimer; preserve it when presenting the data.

## When to use it

Use this tool for questions about reported adverse events, FAERS report counts,
seriousness flags, safety signals, or the date range of available reports.

Use `search_drug_label` when the question asks what an official label lists as
an adverse reaction, warning, contraindication, interaction, or dosage.

## Arguments

| Name | Type | Required | Rules |
| --- | --- | --- | --- |
| `drug_name` | string | yes | Generic or brand name; trimmed; 1–120 Unicode characters. |
| `limit` | integer | no | Maximum reaction aggregates; defaults to 10 and is clamped to 1–25. |

The drug name is matched against the reported medicinal-product name and
openFDA-normalized brand and generic names.

## MCP call example

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "search_drug_safety",
    "arguments": {
      "drug_name": "ibuprofen",
      "limit": 5
    }
  }
}
```

## Response

| Field | Meaning |
| --- | --- |
| `status` | `ok`, `no_results`, or `error`. |
| `source` | `openFDA / FAERS`. |
| `url` | Public openFDA drug-event API documentation page. |
| `error` | Present only for `error`; contains `type`, a safe `message`, and optional upstream `http_status`. |
| `drug` | Normalized drug name used in the search. |
| `reported_events` | Reaction aggregates; always an array. |
| `reported_events[].reaction` | MedDRA preferred term reported for the reaction. |
| `reported_events[].count` | Number of matching reports naming that reaction, not the number of patients or an incidence rate. |
| `seriousness_counts` | Optional report-count split by the FAERS serious flag. |
| `seriousness_counts[].serious` | Whether the bucket represents reports flagged serious. |
| `seriousness_counts[].count` | Reports in that seriousness bucket. |
| `report_date_range.from` | Earliest plausible boundary-report receipt date in `YYYYMMDD` form. |
| `report_date_range.to` | Latest plausible boundary-report receipt date in `YYYYMMDD` form. |
| `boundary_reports` | Optional summaries of the earliest and latest matching reports. |
| `boundary_reports[].safety_report_id` | FAERS safety report identifier, when available. |
| `boundary_reports[].receipt_date` | Plausible receipt date in `YYYYMMDD` form, when available. |
| `boundary_reports[].serious` | Whether that report was flagged serious. |
| `boundary_reports[].seriousness_categories` | Set FAERS seriousness flags, such as `death` or `hospitalization`. |
| `data_last_updated` | Dataset update value returned by openFDA. |
| `disclaimer` | Required interpretation warning configured by `FAERS_DISCLAIMER`. |

Example shape:

```json
{
  "status": "ok",
  "source": "openFDA / FAERS",
  "url": "https://open.fda.gov/apis/drug/event/",
  "drug": "ibuprofen",
  "reported_events": [
    { "reaction": "NAUSEA", "count": 1234 }
  ],
  "seriousness_counts": [
    { "serious": true, "count": 500 },
    { "serious": false, "count": 734 }
  ],
  "report_date_range": { "from": "20040115", "to": "20260330" },
  "data_last_updated": "2026-03-31",
  "disclaimer": "FAERS reports do not establish that the drug caused the reported event. Counts are reports, not incidence rates or probabilities."
}
```

The numbers above illustrate the response shape only; they are not medical data.

## How results are assembled

Dobby first requests reaction counts. If any exist, it concurrently requests a
seriousness breakdown plus the earliest and latest matching reports. These
enrichments are optional: failure to retrieve one does not discard the primary
reaction counts. Implausible receipt dates are omitted rather than guessed.

## Status and failure handling

- `ok`: at least one non-blank reaction aggregate was returned.
- `no_results`: openFDA returned no reports. openFDA represents this case as
  HTTP 404, which Dobby intentionally converts to `no_results` rather than an
  upstream failure.
- `error`: the primary request failed or returned invalid data. This means the
  source could not be checked, not that there are no reports.
- A missing, blank, or overlong `drug_name` is an MCP tool error.

Every call queries openFDA afresh. Transient failures may be retried under
Dobby's configured HTTP retry policy.
