# `search_genetics`

Searches MedlinePlus Genetics for consumer-oriented information about genes,
genetic conditions, inheritance, chromosomes, variants, and genetic mechanisms.

## When to use it

Use this tool for questions such as:

- What does the BRCA1 gene do?
- How is cystic fibrosis inherited?
- What conditions are associated with chromosome 21?

Use `search_health_info` for ordinary disease guidance and
`search_drug_label` for official prescribing information.

## Arguments

| Name | Type | Required | Rules |
| --- | --- | --- | --- |
| `query` | string | yes | Trimmed before use; must contain 1–200 Unicode characters. |

The query can be a gene symbol, condition, chromosome, inheritance pattern, or
another focused genetics topic.

## MCP call example

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "search_genetics",
    "arguments": { "query": "BRCA1" }
  }
}
```

## Response

| Field | Meaning |
| --- | --- |
| `status` | `ok`, `no_results`, or `error`. |
| `source` | `MedlinePlus Genetics`. |
| `url` | MedlinePlus Genetics landing page. |
| `error` | Present only for `error`; contains `type`, a safe `message`, and optional upstream `http_status`. |
| `query` | The trimmed query used for the search. |
| `results` | Matching entries, limited by `MEDICAL_TOOLS_MAX_RESULTS`. Always an array. |
| `results[].name` | Gene symbol, condition name, chromosome, or topic name. |
| `results[].type` | `gene`, `condition`, `chromosome`, `mitochondrial_dna`, or `genetics_topic`. |
| `results[].summary` | Plain-language summary, stripped of markup and bounded by `MEDICAL_TOOLS_MAX_SUMMARY_CHARS`. |
| `results[].source` | Publisher of the entry. |
| `results[].url` | Canonical MedlinePlus Genetics page. |
| `results[].related_genes` | Up to 10 associated gene symbols; omitted when unavailable. |
| `results[].related_conditions` | Up to 10 associated conditions; omitted when unavailable. |
| `results[].inheritance` | Up to 5 inheritance notes; omitted when unavailable. |
| `results[].reviewed` | Upstream review date, when supplied. |
| `results[].published` | Upstream publication date, when supplied. |

Example shape:

```json
{
  "status": "ok",
  "source": "MedlinePlus Genetics",
  "url": "https://medlineplus.gov/genetics/",
  "query": "BRCA1",
  "results": [
    {
      "name": "BRCA1",
      "type": "gene",
      "summary": "The BRCA1 gene helps repair damaged DNA.",
      "source": "MedlinePlus Genetics",
      "url": "https://medlineplus.gov/genetics/gene/brca1/",
      "related_conditions": ["Breast cancer"],
      "reviewed": "2026-01-01"
    }
  ]
}
```

## How results are assembled

Dobby first searches MedlinePlus, then concurrently fetches the detail document
for each result. Detail data supplies the richer summary, related entities,
inheritance, and dates. A failed detail fetch is skipped rather than failing the
whole call. If no detail document succeeds, Dobby keeps the search-level entries.

## Status and failure handling

- `ok`: at least one usable genetics entry was found.
- `no_results`: the search completed but found no usable entry.
- `error`: the main search failed or could not be parsed. It does not establish
  that a gene or condition does not exist.
- A missing, blank, or overlong `query` is an MCP tool error.

Every call fetches fresh upstream data. Transient failures may be retried under
Dobby's configured HTTP retry policy.
