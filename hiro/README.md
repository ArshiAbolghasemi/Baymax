# hiro

The Baymax service: a curated medical knowledge base, the agentic workflow that
answers a question with it, and the HTTP API both are exposed through. One
codebase, three processes — the API, a Celery worker that does the indexing,
and Alembic for migrations.

## What it does

A question arriving at `POST /v1/chat/completions` runs through a small
LangGraph workflow:

```
guardrail ──blocked──> a fixed refusal
          └─allowed──> retrieve documents    ┐
                       retrieve instructions │──> answer ⇄ MCP tools
                       retrieve history      ┘
```

* **guardrail** — a small, separately configured model classifies the message
  as medical or not. A rejection returns the `hiro-blocked` prompt verbatim, so
  the refusal can never be steered by the input.
* **retrieval** — three sources are gathered concurrently and folded into the
  prompt: knowledge base answers matching the question (embedded with bge-m3,
  matched in Qdrant), the operator **instructions** that apply to it, and this
  user's earlier questions in the session. (Document retrieval is commented out
  in `hiro/chat/agent/graph.py` at the moment; instructions and history are
  wired in.)
* **answer** — MedGemma answers, and may call the external medical tools
  (MedlinePlus, DailyMed, openFDA/FAERS, MedlinePlus Genetics) until it has
  enough, ReAct style. **Those tools are not implemented here**: they live in
  the `dobby` MCP server and are discovered over MCP at runtime.

Answers are stored as one answer plus the many questions it satisfies; each
question becomes one vector. Embedding and upserting happen in a Celery task,
so ingestion returns `202` immediately.

## Requirements

* Python 3.14 and [uv](https://docs.astral.sh/uv/).
* The `infra` stacks: Postgres, Redis, Qdrant, MedGemma on :8000, bge-m3 on
  :8001. See `../infra/README.md`.
* The `dobby` MCP server, for the external medical tools. Without it the
  workflow still answers from the knowledge base, but the first tool discovery
  fails per question — start it.
* **Phoenix**, seeded. Every prompt is fetched from it per turn and none ships
  in the code, so hiro cannot answer at all until it is up and seeded. See
  `../phoenix/README.md`.

## Setup

```bash
cp .env.example .env      # then align it with infra/.env
uv sync
./entrypoints/migrate.sh
```

`.env.example` documents every variable. The ones you must get right:

| Variable | Must agree with |
| --- | --- |
| `DATABASE_URL` | `POSTGRES_*` in `infra/.env` |
| `CELERY_BROKER_URL` | `REDIS_PASSWORD` in `infra/.env` |
| `EMBEDDING_BASE_URL`, `EMBEDDING_DIMENSIONS` | the bge-m3 container (1024) |
| `CHATBOT_BASE_URL`, `GUARDRAIL_BASE_URL` | the MedGemma container |
| `QDRANT_URL` | the Qdrant container |
| `MCP_URL` | where dobby is listening, `:8090` by default |
| `CHAT_INSTRUCTION_COLLECTION` | the Qdrant collection your instructions are written to |
| `PHOENIX_BASE_URL` | the Phoenix container — defaults to `:6006`, so only set it if Phoenix is elsewhere |

No prompt is a setting, and none has a default in the code: the wording all
lives in Phoenix. `PHOENIX_PROMPT_TAG` decides which version is read — empty
takes the latest, so a UI edit is live on the next question; `production` (or
any tag) pins hiro to a reviewed version.

## Running

```bash
./entrypoints/api.sh                    # serve on 0.0.0.0:8080
API_RELOAD=true ./entrypoints/api.sh    # auto-reload while developing
./entrypoints/celery.sh                 # the indexing worker
```

Both apply pending migrations first (`RUN_MIGRATIONS=false` to skip) and both
load `.env` themselves, so no `uv run` prefix and no `export` is needed. Port
8080 because 8000 and 8001 belong to the vLLM containers.

Schema changes:

```bash
./entrypoints/makemigrations.sh "add answer source column"   # then read the file
./entrypoints/migrate.sh                                      # apply it
```

Autogenerate never detects a rename — it emits a drop plus an add, which loses
data — so review the generated revision before committing it.

## Usage

Interactive docs are at http://localhost:8080/docs, with pre-filled examples.

**Chat.** OpenAI-compatible, so any OpenAI client works by pointing its base
url here. The conversation is identified by `X-Session-UID`, then body
`session_uid` / `chat_id`, then a deterministic fallback derived from the user
and the first message.

```bash
curl -s localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-Session-UID: 4a1c0d7e-2b3f-4c5d-8e9f-0a1b2c3d4e5f' \
  -d '{"model":"baymax","stream":true,
       "messages":[{"role":"user","content":"What are the side effects of ibuprofen?"}]}'
```

For a terminal instead of curl, use `bashmax`: `cd ../bashmax &&
./entrypoints/chat.sh`.

**Knowledge base.** Store an answer with the questions it satisfies, then
follow its indexing:

```bash
curl -s localhost:8080/v1/knowledge-base/qa \
  -H 'Content-Type: application/json' \
  -d '{"answer":"A fever is a temporary rise in body temperature, usually above 38 C.",
       "questions":["What is a fever?","What temperature counts as a fever?"]}'

curl -s localhost:8080/v1/knowledge-base/qa/<answer_uid>
```

`202` means Postgres has it; `point_uid` on each pair stays null until the
worker has embedded and upserted it.

**Bulk ingestion.** `scripts/ingest_medlineplus.py` pulls the MedlinePlus bulk
files (health topics, genetics, definitions), has MedGemma turn each topic into
QA items, and posts them to the API. It needs the API and MedGemma running.

```bash
uv run python scripts/ingest_medlineplus.py --list-sources
uv run python scripts/ingest_medlineplus.py --limit 2 --dry-run
uv run python scripts/ingest_medlineplus.py --source genetics
```

Runs are resumable: generated output is cached per topic and `state.jsonl`
records what was posted, so an interrupted run neither regenerates nor
duplicates. Delete those under `--data-dir` to force the work again.

## Checks

```bash
uv run ruff check hiro scripts
uv run ruff format --check hiro scripts
```

## Notes worth knowing

**No tool is implemented in this repository.** The agent's tool list is
whatever dobby advertises, discovered once per process on the first question
and wired straight into the graph. A discovery failure is not cached, so a
server that comes up late starts working on the next question — but the tool
names, argument bounds, response limits and disclaimers are all configured in
`dobby/.env`, not here.

**One agent, one model id.** `POST /v1/chat/completions` serves only the model
`GET /v1/models` advertises (`CHAT_AGENT_MODEL_NAME`, default `baymax`) and
refuses anything else with `404`, rather than answering as Baymax under another
name. The agent also supplies its own prompt: system and assistant messages in
a request are ignored, and the count is logged.

**There are no prompt defaults.** `hiro/chat/prompts.py` fetches all six
prompts from Phoenix per turn — by the identifiers the `CHAT_PROMPT_*` settings
name, and there is nothing to fall back to when that
fails — a missing prompt or an unreachable Phoenix fails the run rather than
answering with something the operator never wrote. The guardrail fails closed,
so an outage blocks questions instead of admitting them. The original wording
is in `scripts/seed_prompts.py`, which exists to put it into Phoenix once.

**Instructions are not the knowledge base.** The knowledge base holds *what* to
answer; the instruction collection holds *how* — tone, required caveats,
escalation wording, house rules for a topic. It is a separate Qdrant collection
(`CHAT_INSTRUCTION_COLLECTION`) written outside this service; hiro only
retrieves from it, and creates it empty when missing so a fresh deployment
starts without instructions rather than failing. It must use the same embedding
model and width as the knowledge base, and its points must carry the text under
`CHAT_INSTRUCTION_PAYLOAD_FIELD` (default `instruction`) — a mismatch logs a
warning naming the payload keys it actually found. Because that content is
operator-authored and never user-authored, the answer prompt tells the model to
follow it over what the user asks.

**Configuration is per-package and unprefixed.** Each package owns a
`config.py` reading its own variables, and `hiro/config.py` composes them into
one immutable object behind `get_config()`. Nothing reads `os.environ`
directly.

**The API and the worker can boot together.** Both run migrations on start;
they serialise on a Postgres advisory lock taken in `migrations/env.py`.

**Celery concurrency is deliberately low.** Each task holds a database
connection and calls vLLM, so the useful ceiling is the GPU, not the CPU count.
