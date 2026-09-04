# `search_health_info`

Searches MedlinePlus for patient-friendly information about diseases, symptoms,
diagnosis, treatment, and prevention.

## When to use it

Use this tool for general health questions such as:

- What are the symptoms and causes of asthma?
- How is high blood pressure diagnosed or treated?
- What can help prevent dehydration?

Do not use it for official prescribing instructions, adverse-event report
counts, or detailed genetics questions. Use `search_drug_label`,
`search_drug_safety`, or `search_genetics` respectively.

## Arguments

| Name | Type | Required | Rules |
| --- | --- | --- | --- |
| `query` | string | yes | Trimmed before use; must contain 1–200 Unicode characters. |

Use a concise health topic rather than a long conversational prompt. For
example, `asthma symptoms` is preferable to an entire patient history.

## MCP call example

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "search_health_info",
    "arguments": { "query": "asthma symptoms" }
  }
}
```

## Response

| Field | Meaning |
| --- | --- |
| `status` | `ok`, `no_results`, or `error`. |
| `source` | `MedlinePlus`. |
| `url` | MedlinePlus's health-topics landing page. |
| `error` | Present only when `status` is `error`; contains `type`, a safe `message`, and an optional upstream `http_status`. |
| `query` | The trimmed query used for the search. |
| `results` | Matching topics, limited by `MEDICAL_TOOLS_MAX_RESULTS`. Always an array. |
| `results[].title` | Topic title. |
| `results[].summary` | Plain-language summary, stripped of markup and limited by `MEDICAL_TOOLS_MAX_SUMMARY_CHARS`. |
| `results[].url` | Canonical MedlinePlus page for that topic. |
| `results[].source` | Publisher of the individual topic. |

Example shape:

```json
{
  "status": "ok",
  "source": "MedlinePlus",
  "url": "https://medlineplus.gov/healthtopics.html",
  "query": "asthma symptoms",
  "results": [
    {
      "title": "Asthma",
      "summary": "Asthma is a chronic disease that affects the airways.",
      "url": "https://medlineplus.gov/asthma.html",
      "source": "MedlinePlus"
    }
  ]
}
```

## Status and failure handling

- `ok`: at least one usable topic was found.
- `no_results`: MedlinePlus answered successfully but returned no usable topic.
- `error`: MedlinePlus could not be reached or its response could not be parsed.
  This does not mean the condition does not exist.
- A missing, blank, or overlong `query` is an MCP tool error because the caller
  can correct it and retry.

Every call performs a fresh upstream request. Dobby may retry transient HTTP or
network failures according to its configured HTTP retry policy.
