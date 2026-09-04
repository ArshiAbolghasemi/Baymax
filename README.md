# Baymax

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub](https://img.shields.io/badge/github-ArshiAbolghasemi%2FBaymax-181717.svg)](https://github.com/ArshiAbolghasemi/Baymax)

A self-hosted medical assistant. It answers health questions from a curated
knowledge base, checks authoritative sources — MedlinePlus, DailyMed,
openFDA/FAERS, MedlinePlus Genetics — when the question calls for it, and runs
entirely on your own hardware: open models served by vLLM, no third-party API
in the path.

## The projects

| Project | Language | Used for |
| --- | --- | --- |
| [`hiro`](hiro/README.md) | Python | The service. The knowledge base, the agentic workflow that answers a question, and the OpenAI-compatible HTTP API both are exposed through, plus a Celery worker for indexing. |
| [`dobby`](dobby/README.md) | Go | The MCP server. Owns every external medical tool — their names, limits and disclaimers — and exposes them to any MCP client, hiro's agent included. |
| [`bashmax`](bashmax) | Python | The terminal client. A streaming chat UI against hiro's API and nothing else: no database, no model, no credentials. |
| [`infra`](infra/README.md) | Compose | Everything the above run on: Postgres, Redis, Qdrant, and vLLM serving MedGemma-4B and bge-m3. |

They talk over the network only, so any one of them can be replaced or run
elsewhere:

```
bashmax ──HTTP──> hiro ──MCP──> dobby ──HTTPS──> MedlinePlus, DailyMed, openFDA
                    │
                    └─> Postgres · Redis · Qdrant · vLLM (MedGemma, bge-m3)
```

Keeping the tools in a separate MCP server is deliberate: they are the part
with no application state, they are useful to any MCP client on their own, and
what a person asks them *is* the health information, so their logging and
retries are worth isolating.

## Quickstart

Start from the bottom of the stack.

```bash
# 1. infrastructure — see infra/README.md for the GPU and Hugging Face setup
cd infra && cp .env.example .env      # fill in the token and passwords
docker compose -f database/postgres/postgres.yml up -d
docker compose -f database/redis/redis.yml up -d
docker compose -f vector-store/qdrant/qdrant.yml up -d
docker compose -f llm-serving/vllm/med-gemma-4b/med-gemma-4b.yml up -d
docker compose -f llm-serving/vllm/bge-m3/bge-m3.yml up -d

# 2. the medical tools — no database, no credentials, every source is public
cd ../dobby && cp .env.example .env
go build -o bin/dobby ./cmd/dobby && ./bin/dobby        # MCP on :8090/mcp

# 3. the service
cd ../hiro && cp .env.example .env     # must agree with infra/.env
uv sync && ./entrypoints/migrate.sh
./entrypoints/api.sh                   # :8080, docs at /docs
./entrypoints/celery.sh                # in another shell

# 4. ask it something
cd ../bashmax && cp .env.example .env && ./entrypoints/chat.sh
```

The knowledge base starts empty; fill it with
`hiro/scripts/ingest_medlineplus.py` or by posting to
`/v1/knowledge-base/qa`. Each project's README covers its own configuration and
usage in full.

## Ports

| 5432 | 6379 | 6333 | 8000 | 8001 | 8080 | 8090 | 2112 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Postgres | Redis | Qdrant | MedGemma | bge-m3 | hiro API | dobby MCP | dobby metrics |

## License

MIT. See [LICENSE](LICENSE).

Baymax is not a medical device and gives no medical advice. It surfaces
published reference material; FAERS report counts in particular are not
incidence rates and establish no causality. Ask a clinician.
