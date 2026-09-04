# `search_drug_label`

Retrieves current official US Structured Product Label content from DailyMed.

## When to use it

Use this tool for labeled indications, dosage, contraindications, warnings,
adverse reactions, drug interactions, pregnancy information, or clinical
pharmacology. It answers what the official label says.

Do not use it to estimate adverse-event frequency or inspect FAERS reports. Use
`search_drug_safety` for reported-event data. A label is also not individualized
medical advice; prescribing decisions still require clinical judgment.

## Arguments

| Name | Type | Required | Rules |
| --- | --- | --- | --- |
| `drug_name` | string | yes | Generic or brand name; trimmed; 1–120 Unicode characters. |
| `section` | string | no | Case-insensitive after trimming; defaults to `all`. |

Accepted `section` values are:

- `indications`
- `dosage`
- `contraindications`
- `warnings`
- `adverse_reactions`
- `drug_interactions`
- `pregnancy`
- `clinical_pharmacology`
- `all`

Request one section when only one subject is needed; this keeps the result
smaller. `all` returns every supported section found in the selected label.

## MCP call example

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "search_drug_label",
    "arguments": {
      "drug_name": "ibuprofen",
      "section": "warnings"
    }
  }
}
```

## Response

| Field | Meaning |
| --- | --- |
| `status` | `ok`, `no_results`, or `error`. |
| `source` | `DailyMed`. |
| `url` | Direct DailyMed page for the selected label when found; otherwise the DailyMed landing page. |
| `error` | Present only for `error`; contains `type`, a safe `message`, and optional upstream `http_status`. |
| `drug` | Normalized drug name used for lookup. |
| `section` | Requested section or `all`. |
| `sections` | Object keyed by accepted section name. Always an object, including for one requested section. |
| `setid` | DailyMed set ID for the chosen label. |
| `label_title` | Title returned by DailyMed. |
| `generic_name` | Generic name extracted from the SPL document, when present. |
| `brand_name` | Brand name extracted from the SPL document, when present. |
| `label_metadata.published_date` | Publication date reported by DailyMed. |
| `label_metadata.spl_version` | SPL version for the selected revision. |
| `label_metadata.document_id` | Document identifier from the SPL. |
| `label_metadata.effective_time` | Effective-time value from the SPL. |

Section text is stripped of markup, duplicate matching blocks are removed, and
each returned section is bounded by `MEDICAL_TOOLS_MAX_LABEL_SECTION_CHARS`.
Optional metadata fields are omitted when the source does not provide them.

Example shape:

```json
{
  "status": "ok",
  "source": "DailyMed",
  "url": "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=example-id",
  "drug": "ibuprofen",
  "section": "warnings",
  "sections": {
    "warnings": "Warnings and precautions from the selected label..."
  },
  "setid": "example-id",
  "label_title": "IBUPROFEN tablet",
  "generic_name": "IBUPROFEN",
  "label_metadata": {
    "published_date": "2026-01-01",
    "spl_version": "4"
  }
}
```

## Label selection

A drug name can match labels from many manufacturers. Dobby examines up to 20
candidates and prefers a title beginning with the requested name, then the most
recent publication date, then the highest SPL version. It extracts only the
supported sections from that one selected label.

## Status and failure handling

- `ok`: the selected label contains at least one requested supported section.
- `no_results`: no suitable label was found, or the selected label did not
  contain the requested supported section. `sections` is empty.
- `error`: DailyMed failed, returned invalid data, or supplied malformed SPL.
  This does not mean the drug has no label.
- Missing or invalid arguments are MCP tool errors. An unknown `section` error
  includes the accepted values so the caller can retry correctly.

Every call reads DailyMed afresh. Transient failures may be retried according to
Dobby's configured HTTP retry policy.
