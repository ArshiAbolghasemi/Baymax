# Baymax

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)
[![GitHub](https://img.shields.io/badge/github-ArshiAbolghasemi%2FBaymax-181717.svg)](https://github.com/ArshiAbolghasemi/Baymax)

A local medical assistant. It answers questions about health conditions and medications using public sources (DailyMed, MedlinePlus, openFDA) and an optional curated knowledge base.

**This is not a doctor.** Answers can be incomplete or wrong. Do not use them for diagnosis, dosing, or emergency care. For anything urgent, contact a clinician or emergency services.

openFDA / FAERS counts are *reports*, not incidence rates. They do not prove that a drug caused an event.

**Repository:** [https://github.com/ArshiAbolghasemi/Baymax](https://github.com/ArshiAbolghasemi/Baymax)

---

## Choose a path (read this first)

This repo is two products. Pick **one** based on your machine, then follow only that path.

| | Path A — notebook | Path B — full Baymax |
| --- | --- | --- |
| **Who it is for** | Most GitHub visitors, laptops, no GPU | People with Docker **and** an NVIDIA GPU |
| **What you get** | Jupyter RAG demo + optional Gradio chat | API + terminal chat (hiro + bashmax) |
| **Need Docker?** | No | Yes |
| **Need NVIDIA GPU?** | No. Use Ollama `medgemma:4b` for answers | Yes, for the vLLM containers |
| **Need Python 3.14?** | Any 3.10+ Jupyter kernel is fine | Yes (uv can install it) |
| **Time to first result** | ~15–30 minutes | ~30–90 minutes (model download) |
| **Start at** | [Path A](#path-a--notebook-no-docker-no-gpu) | [Path B](#path-b--full-assistant-docker--gpu) |

If you are unsure: **Path A**.

```text
Do you have Docker Desktop AND an NVIDIA GPU with ~16 GB VRAM?
   │
   ├─ No  →  Path A (drug.ipynb)
   │
   └─ Yes →  Path B (infra + hiro + bashmax)
```

---

## Contents

- [Choose a path](#choose-a-path-read-this-first)
- [Path A — notebook](#path-a--notebook-no-docker-no-gpu)
- [Path B — full assistant](#path-b--full-assistant-docker--gpu)
- [How it works](#how-it-works)
- [Repository layout](#repository-layout)
- [HTTP API](#http-api)
- [Agent tools](#agent-tools)
- [Configuration](#configuration)
- [Optional: ingest MedlinePlus](#optional-ingest-medlineplus-into-the-knowledge-base)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Path A — notebook (no Docker, no GPU)

You will open `drug.ipynb`, pull a small public corpus, embed it on disk, and ask questions. Generation is **off until Ollama MedGemma is running**. That is the laptop-friendly path from the [FreeCodeCamp MedGemma + Ollama guide](https://www.freecodecamp.org/news/build-your-own-healthcare-ai-assistant-with-medgemma-ollama-and-open-webui/). Loading full Hugging Face weights in-process is optional and heavy.

### A1. Clone

```bash
git clone https://github.com/ArshiAbolghasemi/Baymax.git
cd Baymax
```

PowerShell:

```powershell
git clone https://github.com/ArshiAbolghasemi/Baymax.git
cd Baymax
```

### A2. Install a notebook kernel (one time)

You need Python and the Jupyter kernel. In a terminal **in this folder**:

```bash
python -m pip install --upgrade pip
python -m pip install ipykernel notebook
```

**You should see:** pip listing packages, then a prompt again with no traceback.

Open the folder in [VS Code](https://code.visualstudio.com/), [Cursor](https://cursor.com/), JupyterLab, or upload `drug.ipynb` to Google Colab.

### A3. Open the notebook and pick a kernel

1. Open [`drug.ipynb`](drug.ipynb).
2. Top-right: **Select Kernel** → your Python 3 interpreter.
3. If the list is empty: **Select Another Kernel → Python Environments**, then pick Python 3.

Colab: Runtime is assigned automatically. For answers on Colab, either attach a GPU or skip generation (retrieval still works).

### A4. Optional: local MedGemma via Ollama (recommended for answers)

Retrieval works without this. For generated answers on a laptop:

1. Install [Ollama](https://ollama.com/download) (Windows installer is fine).
2. In a terminal:

```powershell
ollama pull medgemma:4b
```

3. Confirm the server: open `http://localhost:11434` — you should see `Ollama is running`.
4. Re-run the notebook's MedGemma cell. `LLM_BACKEND = "auto"` will select Ollama.

The 4B pull is about 3.3 GB and is meant for ~8 GB RAM. Do **not** set the backend to `transformers` unless you have a GPU and a Hugging Face token for [google/medgemma-4b-it](https://huggingface.co/google/medgemma-4b-it).

This is the same local-model idea as the [FreeCodeCamp MedGemma + Ollama guide](https://www.freecodecamp.org/news/build-your-own-healthcare-ai-assistant-with-medgemma-ollama-and-open-webui/). This notebook adds RAG (DailyMed / MedlinePlus / openFDA) on top.

### A5. Run the cells from the top

1. Run the first **code** cell (`%pip install ...`). Wait until it finishes.
2. Continue with **Run All**, or Shift+Enter cell by cell.
3. If Ollama is not running, generation prints `[LLM skipped]` and still shows retrieved sources.

The first run downloads `intfloat/multilingual-e5-base` (embedding model) and talks to DailyMed / MedlinePlus / openFDA. That needs internet.

**You should see:**

- After install: no red traceback, kernel still idle
- After the loaders: counts such as `DailyMed documents: 5`, `MedlinePlus documents: …`
- After embeddings: `Vector store ready at .../data/notebook/medical_db`
- After the MedGemma cell: `Active backend: ollama` (if A4 is done) or `Active backend: none`
- After `medical_chat(...)`: a sourced answer, or `[LLM skipped] Retrieved N passage(s) from …`

If the Medicib crawl fails, keep going — the three official APIs are enough to build a corpus.

### A6. Ask a question

A later cell runs `medical_chat("What is aspirin used for?")`. The last code cell starts a local Gradio chat. Open the URL it prints (usually `http://127.0.0.1:7860`).

Example questions:

- What is metformin used for?
- What is hypertension?
- What are side effects of aspirin?

On a later run, set `SKIP_CRAWL = True` to reuse `data/notebook/traditional_medicine.json`.

Outputs (gitignored under `data/`):

- `data/notebook/corpus.csv` / `corpus.json`
- `data/notebook/traditional_medicine.json`
- `data/notebook/medical_db/` (Chroma)

### Notebook vs the full app

| | Path A notebook | Path B hiro |
| --- | --- | --- |
| Vector store | Chroma on disk | Qdrant |
| Embeddings | multilingual-e5 in-process | bge-m3 via vLLM |
| LLM | Transformers in-process (optional) | vLLM OpenAI API |
| Tools | None (context is pre-indexed) | Live DailyMed / MedlinePlus / FAERS / Genetics |
| Guardrail | Prompt wording only | Dedicated 1/0 classifier node |
| Sessions | None | Postgres `session` / `message` |
| UI | Gradio | bashmax + any OpenAI client |

The production service does **not** import this notebook. They share sources, not a runtime.

---

## Path B — full assistant (Docker + GPU)

hiro (API + agent) + bashmax (terminal client) + Docker services.

**Hardware (be honest with yourself before starting):**

| Piece | What you need |
| --- | --- |
| Docker Desktop (or Engine) + Compose v2 | Required |
| NVIDIA GPU + current driver + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) | Required for the vLLM containers in this repo |
| VRAM | **~16 GB** to run MedGemma 4B **and** bge-m3 on one GPU (compose uses 0.60 + 0.15 GPU memory). An 8 GB card may run **one** of them if you lower utilization; it will not comfortably run both at the defaults |
| Disk | Several GB for Docker images + Hugging Face weights |
| RAM | 16 GB system RAM is a practical minimum besides VRAM |
| Hugging Face | Account, token, and accepted terms on [MedGemma-4B-IT](https://huggingface.co/google/medgemma-4b-it) |

No GPU? Use [Path A](#path-a--notebook-no-docker-no-gpu), or run only Postgres/Redis/Qdrant and point `CHATBOT_BASE_URL` / `EMBEDDING_BASE_URL` at some other OpenAI-compatible server you already have.

### B1. Install tools

1. [Git](https://git-scm.com/)
2. [Docker Desktop](https://docs.docker.com/get-docker/) — start it and wait until it says running
3. [uv](https://docs.astral.sh/uv/getting-started/installation/) — Python 3.14 **does not** have to be your system Python. uv can install it:

```bash
# macOS / Linux / Git Bash / WSL
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen the terminal, then:

```bash
uv python install 3.14
uv --version
```

**You should see:** a `uv` version line, not “command not found”.

### B2. Clone and create env files

```bash
git clone https://github.com/ArshiAbolghasemi/Baymax.git
cd Baymax

cp infra/.env.example infra/.env
cp hiro/.env.example  hiro/.env
cp bashmax/.env.example bashmax/.env
```

PowerShell:

```powershell
git clone https://github.com/ArshiAbolghasemi/Baymax.git
cd Baymax

Copy-Item infra/.env.example infra/.env
Copy-Item hiro/.env.example hiro/.env
Copy-Item bashmax/.env.example bashmax/.env
```

Edit **`infra/.env`**:

- `HUGGING_FACE_HUB_TOKEN=hf_...` (your token)
- Change `change-me` on **both** `POSTGRES_PASSWORD` and `REDIS_PASSWORD` to a password you invent

Edit **`hiro/.env`** so the URLs use that **same** password:

```text
DATABASE_URL=postgresql+psycopg://baymax:YOUR_PASSWORD@localhost:5432/baymax
CELERY_BROKER_URL=redis://:YOUR_PASSWORD@localhost:6379/0
CELERY_RESULT_BACKEND=redis://:YOUR_PASSWORD@localhost:6379/1
```

Leave **`bashmax/.env`** as `BAYMAX_URL=http://localhost:8080/v1` for a local API.

If the passwords do not match across `infra/.env` and `hiro/.env`, Postgres and Redis will refuse connections.

### B3. Start infrastructure

Run these from the **repository root** (`Baymax/`). Compose `env_file` paths are relative to each YAML file, so this works from the root.

```bash
docker compose -f infra/database/postgres/postgres.yml up -d
docker compose -f infra/database/redis/redis.yml up -d
docker compose -f infra/vector-store/qdrant/qdrant.yml up -d
```

GPU hosts — first start downloads weights and can take 10–30 minutes:

```bash
docker compose -f infra/llm-serving/vllm/med-gemma-4b/med-gemma-4b.yml up -d
docker compose -f infra/llm-serving/vllm/bge-m3/bge-m3.yml up -d
```

Check:

```bash
docker ps
curl -s http://localhost:6333/readyz
curl -s http://localhost:8000/health
curl -s http://localhost:8001/health
```

**You should see:**

- `docker ps` lists `postgres`, `redis`, `qdrant`, and (if started) `medgemma-4b` and `bge-m3` with status `healthy` or `starting`
- Qdrant `readyz` returns an OK body
- vLLM `/health` returns HTTP 200 once the model is loaded (MedGemma’s healthcheck allows several minutes)

If MedGemma logs `gated repo` or `401`, the Hugging Face token is missing or you have not accepted the model terms.

### B4. Start hiro (API)

```bash
cd hiro
uv sync
```

**You should see:** uv creating a `.venv` and installing packages, ending without an error.

Unix / Git Bash / WSL (loads `.env`, migrates, then serves on port 8080):

```bash
./entrypoints/api.sh
```

Auto-reload while coding:

```bash
API_RELOAD=true ./entrypoints/api.sh
```

Windows PowerShell (Celery’s default `prefork` pool does **not** work on Windows):

```powershell
cd hiro
uv sync
uv run alembic upgrade head
uv run uvicorn api.app:app --host 0.0.0.0 --port 8080
```

Port **8080** is intentional: 8000 and 8001 belong to vLLM.

**You should see:** a uvicorn “started” line. Then open:

- Swagger: [http://localhost:8080/docs](http://localhost:8080/docs)
- ReDoc: [http://localhost:8080/redoc](http://localhost:8080/redoc)
- Liveness: [http://localhost:8080/health](http://localhost:8080/health) → `{"status":"ok"}`

Keep this terminal open.

### B5. Start the worker (second terminal)

Indexing QA pairs into Qdrant happens here, not in the API process.

Unix:

```bash
cd hiro
./entrypoints/celery.sh
```

Windows PowerShell — use `solo`:

```powershell
cd hiro
uv run celery --app worker.app:celery_app worker --pool solo --concurrency 1 --loglevel info
```

**You should see:** Celery “ready” / consumer started. Leave it running.

### B6. Chat with bashmax (third terminal)

```bash
cd bashmax
uv sync
./entrypoints/chat.sh
```

PowerShell:

```powershell
cd bashmax
uv sync
uv run python -m cli
```

**You should see:** a “Baymax” banner with endpoint `http://localhost:8080/v1`, then a `you ›` prompt. Type a medical question and press Enter.

In-session commands:

| Command | Action |
| --- | --- |
| `/help` | List commands |
| `/new` | New session UUID, cleared client history |
| `/session` | Print the current session uid |
| `/models` | `GET /v1/models` |
| `/clear` | Clear the screen |
| `/raw` | Toggle markdown rendering |
| `/quit` | Leave (`/exit`, `/q`, or Ctrl-D) |

Flags (or `BAYMAX_URL`, `BAYMAX_MODEL`, `BAYMAX_API_KEY` in `bashmax/.env`):

```text
--url http://localhost:8080/v1
--model baymax
--session <uuid>          resume a conversation
--user <name>             stable user identity
--raw                     print markdown as plain text
--timeout 300
```

There is **no authentication** today (`BAYMAX_API_KEY` is sent and ignored). Do not expose the API on the public internet.

---

## How it works

hiro runs a LangGraph workflow. A question never goes straight to the model:

```text
question
   │
   ▼
guardrail ──(not medical)──► fixed refusal
   │
   ▼ (medical)
retrieve session history          (Qdrant KB retrieval exists in code; see below)
   │
   ▼
MedGemma (ReAct) ──tool call──► MedlinePlus / DailyMed / openFDA / Genetics
   │                                    │
   └────────◄──── tool result ──────────┘
   │
   ▼
streamed answer  (OpenAI-compatible SSE)
```

**Knowledge-base retrieval** (`retrieve_documents`) is implemented and ingest writes embeddings into Qdrant, but the live graph currently only wires `retrieve_history`. To also retrieve stored QA pairs, uncomment `retrieve_documents` in [`hiro/chat/agent/graph.py`](hiro/chat/agent/graph.py) (`RETRIEVAL_NODES` and `builder.add_node`).

The three layers:

| Piece | Path | Role |
| --- | --- | --- |
| **hiro** | [`hiro/`](hiro/) | FastAPI service, LangGraph agent, Celery indexer, MedlinePlus ingest |
| **bashmax** | [`bashmax/`](bashmax/) | Terminal client for the OpenAI-compatible chat API |
| **infra** | [`infra/`](infra/) | Docker Compose for Postgres, Redis, Qdrant, vLLM (MedGemma + bge-m3) |
| **notebook** | [`drug.ipynb`](drug.ipynb) | Standalone RAG prototype (Path A) |

hiro and bashmax are **separate** Python projects (`package = false` in uv). bashmax imports nothing from hiro; it is a pure HTTP client.

---

## Repository layout

```text
Baymax/
├── README.md                 ← you are here
├── LICENSE                   ← MIT
├── drug.ipynb                ← Path A prototype
├── hiro/                     ← API + agent + worker + ingest
│   ├── api/                  ← FastAPI app, health, middleware
│   ├── chat/                 ← OpenAI-compatible routes + LangGraph agent
│   ├── knowledge_base/       ← QA storage, Qdrant indexing, HTTP ingest
│   ├── clients/              ← embedding, Qdrant, shared HTTP config
│   ├── db/                   ← SQLAlchemy + Postgres
│   ├── worker/               ← Celery app
│   ├── migrations/           ← Alembic
│   ├── scripts/              ← MedlinePlus bulk ingest
│   └── entrypoints/          ← api.sh, celery.sh, migrate.sh, …
├── bashmax/                  ← streaming terminal client
│   ├── cli/                  ← argparse loop, HTTP, Rich rendering
│   └── entrypoints/chat.sh
└── infra/                    ← compose files, not an application
    ├── database/postgres/
    ├── database/redis/
    ├── vector-store/qdrant/
    └── llm-serving/vllm/     ← med-gemma-4b + bge-m3
```

---

## HTTP API

hiro speaks a small OpenAI-compatible surface plus a knowledge-base ingest API.

### Chat

`GET /v1/models` — advertised name is `CHAT_AGENT_MODEL_NAME` (default `baymax`).

`POST /v1/chat/completions`

```json
{
  "model": "baymax",
  "messages": [{"role": "user", "content": "What is metformin used for?"}],
  "stream": true,
  "session_uid": "optional-uuid"
}
```

- `stream: true` — SSE (`text/event-stream`), same chunk shape as OpenAI, ending with `data: [DONE]`
- `stream: false` — a single `chat.completion` JSON body
- Session identity (first match wins): header `X-Session-UID`, body `session_uid`, body `chat_id`, then a deterministic UUID from user + first message
- Response header `X-Session-UID` is always set
- Request header `X-Request-ID` is echoed and flows into Celery logs

Non-medical questions are refused with `CHAT_BLOCKED_MESSAGE`. The guardrail model must answer `1` or `0`; anything else is treated as `0` (blocked).

### Knowledge base

| Method | Path | Result |
| --- | --- | --- |
| `POST` | `/v1/knowledge-base/qa` | `202` — stored, indexing queued |
| `GET` | `/v1/knowledge-base/qa/{answer_uid}` | Indexing progress + pair `point_uid`s |

Questions are de-duplicated case-insensitively. Existing question text is reused rather than inserted twice.

### Ops

`GET /health` — process liveness only (does not check Postgres, Redis, or Qdrant).

---

## Agent tools

When the answer model needs current official text, it can call:

| Tool | Upstream | Use for |
| --- | --- | --- |
| `search_health_info` | MedlinePlus search (`healthTopics`) | Diseases, symptoms, prevention |
| `search_drug_label` | DailyMed SPL XML | Indications, dosage, warnings, interactions, pregnancy, … |
| `search_drug_safety` | openFDA FAERS | Reported adverse events (**not** incidence) |
| `search_genetics` | MedlinePlus Genetics | Genes, inherited conditions, chromosomes |

Tools are retried on transient HTTP statuses, cached in-process, and return a structured error payload instead of crashing the graph when a vendor is down.

---

## Configuration

All hiro settings come from the **environment** (and `hiro/.env` in development). There is no YAML settings file. Names are unprefixed: `DATABASE_URL`, `QDRANT_URL`, …

[`hiro/.env.example`](hiro/.env.example) documents every variable. These must be set before `api.sh` / `celery.sh` will start:

```text
DATABASE_URL
CELERY_BROKER_URL
EMBEDDING_BASE_URL
EMBEDDING_MODEL
QDRANT_URL
```

Defaults that matter:

| Variable | Default | Meaning |
| --- | --- | --- |
| `CHATBOT_BASE_URL` | `http://localhost:8000/v1` | MedGemma / any OpenAI-compatible chat |
| `CHATBOT_MODEL` | `medgemma-4b` | Must match vLLM `--served-model-name` |
| `EMBEDDING_BASE_URL` | `http://localhost:8001/v1` | bge-m3 |
| `EMBEDDING_DIMENSIONS` | `1024` | Must match the embedding model |
| `KNOWLEDGE_BASE_COLLECTION` | `baymax_v1` | Qdrant collection |
| `CHAT_RETRIEVAL_TOP_K` | `5` | Used when KB retrieval is enabled |
| `CHAT_HISTORY_TURNS` | `5` | Earlier user questions in the prompt |
| `API_PORT` (entrypoint) | `8080` | uvicorn bind port |

A bare `postgresql://` URL is upgraded to `postgresql+psycopg://` so the same string works for psql, Alembic, and the app.

---

## Optional: ingest MedlinePlus into the knowledge base

Path B only. Skip this on a first run — live tools already query DailyMed, MedlinePlus, and openFDA.

[`hiro/scripts/ingest_medlineplus.py`](hiro/scripts/ingest_medlineplus.py) downloads official MedlinePlus bulk XML, asks the chat model to write grounded question/answer items, and POSTs them to `POST /v1/knowledge-base/qa`. The API stores rows in Postgres; the Celery worker embeds them into Qdrant.

Covered sources (only what NLM publishes as files):

| `--source` | Content |
| --- | --- |
| `health-topics` | Health Topics daily XML (English/Spanish) |
| `genetics` | Genes, conditions, chromosomes, mtDNA |
| `definitions` | Vitamins, minerals, nutrition, fitness, general health terms |

**Not** ingested (licensed / no bulk file): Drugs & Supplements, Medical Tests, Medical Encyclopedia. Those are queried live through agent tools instead.

The API and the chat model (`--llm-base-url`) must be running. Caches live under `data/` (gitignored).

```bash
cd hiro

uv run python scripts/ingest_medlineplus.py --list-sources
uv run python scripts/ingest_medlineplus.py --limit 2 --dry-run
uv run python scripts/ingest_medlineplus.py --source genetics --limit 20
uv run python scripts/ingest_medlineplus.py
```

| Flag | Meaning |
| --- | --- |
| `--limit N` | First N topics only (start here) |
| `--dry-run` | Generate JSON, do not POST |
| `--parse-only` | Download/parse, do not call the LLM |
| `--language english\|spanish\|all` | Health-topics language filter |
| `--regenerate` | Ignore the per-topic generation cache |
| `--api-url` | Default `http://localhost:8080` |
| `--llm-base-url` / `--model` | OpenAI-compatible generator |

Re-runs are cheap: `data/medlineplus/generated/` caches model output and `state.jsonl` records posted answer hashes so nothing is inserted twice.

Manual ingest:

```bash
curl -s http://localhost:8080/v1/knowledge-base/qa \
  -H "Content-Type: application/json" \
  -d "{\"answer\":\"A fever is a temporary rise in body temperature, usually above 38 C.\",\"questions\":[\"What is a fever?\"]}"
```

`202` means Postgres has the row. Poll `GET /v1/knowledge-base/qa/{answer_uid}` until `indexed_pairs == total_pairs`.

---

## Development

```bash
cd hiro
uv sync --group dev
uv run ruff check .
uv run ruff format .

cd ../bashmax
uv sync --group dev
uv run ruff check .
```

New database migration (database must already be at head):

```bash
cd hiro
./entrypoints/makemigrations.sh "add column whatever"
# read the generated file, then
./entrypoints/migrate.sh
```

Windows: `uv run alembic revision --autogenerate -m "add column whatever"`.

Logging: `LOG_LEVEL=DEBUG` adds per-batch embedding and per-query lines. Every HTTP request gets a correlation id (`X-Request-ID`).

Issues and pull requests: [https://github.com/ArshiAbolghasemi/Baymax](https://github.com/ArshiAbolghasemi/Baymax). Please do not open issues asking the assistant for personal medical advice.

---

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Not sure which path to run | No Docker or no NVIDIA GPU → [Path A](#path-a--notebook-no-docker-no-gpu) |
| `python` / `uv` not found | Install Git, then uv ([B1](#b1-install-tools)). Restart the terminal |
| `uv` cannot find Python 3.14 | `uv python install 3.14` — you do not need a system-wide 3.14 |
| `git clone <this-repository-url>` | Use `https://github.com/ArshiAbolghasemi/Baymax.git` |
| Notebook “No kernel” | [A2](#a2-install-a-notebook-kernel-one-time), then pick Python in the kernel picker |
| Notebook `%pip` errors | Internet required; run that cell again |
| Notebook crawl / Medicib fails | Continue — DailyMed, MedlinePlus, and openFDA still fill the corpus |
| `RuntimeError: No documents survived` | Check network access to those three APIs |
| PC freezes on MedGemma | Use Ollama `medgemma:4b`, not the Transformers backend |
| `api.sh` exits on missing env | Copy `hiro/.env.example` → `hiro/.env` and fill the required URLs |
| `connection refused` on 5432 / 6379 / 6333 | Matching compose file is not up, or the port is already taken |
| `password authentication failed` | `POSTGRES_*` in `infra/.env` must match `hiro/.env` `DATABASE_URL` |
| Redis `NOAUTH` | `CELERY_BROKER_URL` must include `:password@` from `REDIS_PASSWORD` |
| vLLM `gated repo` / 401 | Accept MedGemma terms; put a valid token in `infra/.env` |
| Embedding dimension error | `EMBEDDING_DIMENSIONS` must be `1024` for bge-m3; changing it does not migrate an existing collection |
| Worker never indexes | Celery must be running; look for `knowledge_base.index_qa` |
| Guardrail blocks everything | `CHAT_GUARDRAIL_SYSTEM_PROMPT` must require a single `1` or `0` |
| Windows Celery crash | Use `--pool solo` (prefork uses `os.fork`) |
| Slow first notebook run | E5 download + 1.5s crawl delay are expected |

---

## License

MIT. See [`LICENSE`](LICENSE).

Upstream data (DailyMed, MedlinePlus, openFDA, site crawls) remains under each publisher's terms. This project does not grant you rights to redistribute those corpora.
