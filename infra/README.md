# infra

Every stateful service and model server Baymax runs on, as standalone Docker
Compose files. Nothing application-specific lives here: `hiro` connects to
these over the network and can just as well point at managed equivalents.

| Service | Image | Port | Used for |
| --- | --- | --- | --- |
| `postgres` | `postgres:17-alpine` | 5432 | knowledge base and chat tables |
| `redis` | `redis:8-alpine` | 6379 | Celery broker and result backend |
| `qdrant` | `qdrant/qdrant:v1.19.0` | 6333 / 6334 | vector store for knowledge base retrieval |
| `medgemma-4b` | `vllm/vllm-openai` | 8000 | generation: the answer model, the guardrail, and QA generation during ingestion |
| `bge-m3` | `vllm/vllm-openai` | 8001 | embeddings, 1024 dimensions |

## Requirements

* Docker with the Compose plugin.
* For the two vLLM stacks only: an NVIDIA GPU with the container toolkit
  installed. They reserve 60% (MedGemma) and 15% (bge-m3) of one GPU's memory
  and are sized to share it — roughly 16GB VRAM for both, plus ~30GB of disk
  for the shared Hugging Face cache volume.
* A Hugging Face token, because `google/medgemma-4b-it` is gated: create one at
  https://huggingface.co/settings/tokens **and** accept the terms on the model
  page, or vLLM fails at startup with a 401 / "gated repo".

Postgres, Redis and Qdrant have no GPU requirement and run anywhere.

## Setup

```bash
cp .env.example .env      # then fill in HUGGING_FACE_HUB_TOKEN and the passwords
```

The compose files read this `.env` directly, so the commands below work from
any directory. Whatever you set for `POSTGRES_*` and `REDIS_PASSWORD` must
match `DATABASE_URL` and `CELERY_BROKER_URL` in `hiro/.env` — they are the same
credentials written twice.

## Usage

Each file is independent; start only what you need.

```bash
docker compose -f database/postgres/postgres.yml up -d
docker compose -f database/redis/redis.yml up -d
docker compose -f vector-store/qdrant/qdrant.yml up -d
docker compose -f llm-serving/vllm/med-gemma-4b/med-gemma-4b.yml up -d
docker compose -f llm-serving/vllm/bge-m3/bge-m3.yml up -d
```

Every service has a healthcheck, so `docker ps` tells you when it is actually
ready. The first start of a vLLM stack downloads weights and can take several
minutes — that is why their `start_period` is 2–5 minutes; follow it with
`docker compose -f <file> logs -f`.

Check them by hand:

```bash
curl -s localhost:8000/v1/models     # medgemma-4b
curl -s localhost:8001/v1/models     # bge-m3
curl -s localhost:6333/readyz        # qdrant
docker exec -it postgres psql -U baymax -d baymax -c '\dt'
```

Stop a stack with `down`, and add `-v` to also drop its volume — that erases
the database, the vectors, or the model cache, so it is not part of a normal
restart.

```bash
docker compose -f database/postgres/postgres.yml down
```

## Notes worth knowing

**Data survives restarts.** Postgres, Redis (append-only) and Qdrant each own a
named volume, and the Hugging Face cache is shared between the two vLLM stacks
so a model is downloaded once.

**MedGemma is served with tool calling on.** `--enable-auto-tool-choice`, the
hermes parser and a custom chat template are what let hiro's agent call the
MCP tools; serving the model without them gives you an assistant that can only
talk.

**Qdrant runs unauthenticated.** There is no API key by default, which is fine
for a local bind but not for an exposed host — set
`QDRANT__SERVICE__API_KEY` in `qdrant.yml` and `QDRANT_API_KEY` in `hiro/.env`
together if that changes.

**The embedding width is a contract.** bge-m3 emits 1024 dimensions and
collections are created to match; changing the model means changing
`EMBEDDING_DIMENSIONS` in `hiro/.env` and re-indexing.
