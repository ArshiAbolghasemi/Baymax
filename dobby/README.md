# dobby

An MCP (Model Context Protocol) server that exposes Baymax's authoritative
medical reference tools to any MCP client. It is a Go port of the external
tools in hiro's Python `chat.agent.tools` package, kept behaviourally
identical: same tool names, same arguments, same result payloads, same limits
and disclaimers.

## Tools

| Tool | Arguments | Result |
| --- | --- | --- |
| `search_health_info` | `query` | `{query, results[{title, summary, url, source}]}` |
| `search_drug_label` | `drug_name`, `section` | `{drug, section, sections{}, setid, label_title, generic_name, brand_name, label_metadata}` |
| `search_drug_safety` | `drug_name`, `limit` | `{drug, reported_events[], seriousness_counts[], report_date_range, boundary_reports[], disclaimer}` |
| `search_genetics` | `query` | `{query, results[{name, type, summary, related_genes, related_conditions, inheritance}]}` |

Every result also carries `status`, `source`, `url`, and `error` when the
retrieval failed. The sources are MedlinePlus, DailyMed, openFDA/FAERS and
MedlinePlus Genetics; none of them needs an API key.

## Layout

```
cmd/dobby/main.go               the binary: one call into internal/dobby
internal/dobby                  process lifecycle: signals, App, metrics server
internal/config                 the whole configuration, in one global Conf
internal/logging                zap logger, tee'd to a JSON file and the console
internal/metrics                tool_call_* / upstream_* series
internal/mcpserver              the MCP server, its transport and middleware
internal/httpx                  outbound HTTP: timeouts and bounded retries
internal/tools                  one file per tool, plus the shared registry
internal/medline                parsing for the NLM service both MedlinePlus tools use
internal/textutil               markup stripping and length budgets
```

## Configuration

Everything is read from the environment (or a local `.env`), with a working
default in `internal/config/config.go`. See `.env.example` for the full list.

The source and limit variables deliberately reuse the names hiro's Python
configuration already reads (`MEDLINEPLUS_SEARCH_URL`, `MEDICAL_TOOLS_*`,
`FAERS_DISCLAIMER`), so one `.env` or one ConfigMap configures both processes
and they cannot drift apart.

`ENABLED_TOOLS` selects and orders the exposed subset. Leaving it empty exposes
every tool.

## Running

No database, no compose stack, no credentials — every source is a public API.

```bash
go build -o bin/dobby ./cmd/dobby
./bin/dobby                   # MCP on :8080/mcp, metrics on :2112
```

Any MCP client that speaks streamable HTTP can point at
`http://localhost:8080/mcp`.

## Testing it by hand

Both headers are required; the server rejects a request without the `Accept`
pair.

```bash
curl -s localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

curl -s localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call",
       "params":{"name":"search_drug_safety",
                 "arguments":{"drug_name":"ibuprofen","limit":3}}}'

curl -s localhost:2112/metrics | grep -E 'tool_call|upstream_'
curl -s localhost:2112/healthz
```

In stateless mode (the default) each request is independent, so there is no
session id to carry between calls.

To exercise a tool without hitting a real upstream, point its URL at a local
stub: `OPENFDA_EVENT_URL=http://127.0.0.1:8099/ ./bin/dobby`.

## Design decisions worth knowing

**A failed retrieval is a result, not a protocol error.** Every tool returns
`status: ok | no_results | error`. A model that asked about a drug label needs
to be able to say "I could not check", which it cannot do if the call fails at
the transport level. Only an invalid *argument* fails the call, because that is
the one thing the model can fix and retry.

**`no_results` and `error` are kept apart deliberately.** openFDA answers `404`
when a search matches no reports; treating that as a failure — or as an empty
result — would let a model read "no reported adverse events" out of "we could
not reach FDA". That 404 maps to `no_results`; everything else that fails is
`error`, and `404` is deliberately absent from the retryable statuses.

**The question is the sensitive data.** `query` and `drug_name` are redacted to
their length in the logs. What a person asks these tools *is* the health
information, so it must not sit in `access.log`; the rest of a call is logged
in full so it can still be traced.

**Schemas come from the Go types.** `mcp.WithOutputSchema[T]` derives the
result schema from the same struct the handler returns, and both directions are
validated at runtime, so the advertised contract cannot drift from the code.
Argument bounds are advertised in the input schema *and* enforced in the
handler, because a client is free to ignore a schema.

**Everything is bounded.** Summaries, label sections, result counts and response
bodies all have caps, so a verbose upstream document cannot consume a client's
context window.

**Implausible upstream data is dropped, not corrected.** FAERS contains
transcription errors — reports dated in the year 3004 are really in the
dataset. A receipt date outside a plausible window is omitted rather than
guessed at.

## Tests

```bash
go test ./...                    # unit tests
go test -race ./...              # what CI should run
```

Everything runs with no setup. Upstreams are stubbed with `httptest`, so no
test reaches the real MedlinePlus, DailyMed or openFDA APIs.

## Checks

```bash
go build ./... && go vet ./...
golangci-lint run ./...
```
