# phoenix

[Arize Phoenix](https://github.com/Arize-ai/phoenix) as Baymax runs it: the
store of record for every prompt hiro sends.

hiro ships no prompt text. The persona, the answering rules, the guardrail
classifier, the refusal and the empty-retrieval stand-ins are all versioned
here and edited in the UI, so changing how the assistant talks is not a deploy.
The flip side is that **Phoenix is a hard dependency of answering**: while it is
down or unseeded, hiro cannot build a prompt and the chat endpoint fails
instead of falling back to something plausible.

Phoenix is also an LLM tracing platform and the container accepts OTLP on 4317.
Nothing in Baymax sends traces today; the port is exposed so that instrumenting
hiro later needs no change here.

## Setup

```bash
cp .env.example .env
docker compose -f phoenix.yml up -d
```

The UI is at http://localhost:6006, and that same port serves the REST API the
client reads. State is SQLite under a named volume, so Phoenix does not depend
on the Postgres in `../infra` and can run on its own; point
`PHOENIX_SQL_DATABASE_URL` at Postgres if you outgrow that.

## Testing the agent from the playground

`OPENAI_BASE_URL` in `.env` points Phoenix's OpenAI provider at hiro's own API
(`:8080/v1`) rather than at OpenAI, so a prompt run in the playground goes
through the whole agent — guardrail, retrieval, MCP tools — and not just the
raw model. Pick the **OpenAI** provider and the model **baymax**, the id hiro
advertises at `GET /v1/models`; the seeded prompts already carry that model
name, so an opened prompt is preset correctly.

No API key is needed. With a base url set and `OPENAI_API_KEY` unset, Phoenix
sends a placeholder key and hiro does not check it. Do not set a real
`OPENAI_API_KEY` here: Phoenix then refuses per-request custom base urls, to
avoid sending a server-configured key to a client-supplied host.

**Run `hiro-probe`, not `hiro-answer`.** hiro reads the last user message as
the question and applies its own prompt, fetched from this same Phoenix, so
sending it a rendered `hiro-answer` would wrap that prompt a second time.
`hiro-probe` exists for this: one user message, `{{question}}` — what a person
would actually type. System and assistant messages you send are dropped, and
hiro logs how many it ignored.

To test the wording of `hiro-answer` itself, that is a different target: point
the playground at vLLM (`http://medgemma-4b:8000/v1`, model `medgemma-4b`),
where the prompt is the whole request.

**Only `baymax` is served.** hiro answers requests for the model it advertises
at `GET /v1/models` and refuses every other with `404 model does not exist`,
the way OpenAI does — so picking `gpt-4o` in the playground fails loudly
instead of returning Baymax's answer under another model's name.

## Adding another model

Nothing here is an allowlist Phoenix enforces; each provider simply needs
credentials before it can be selected, and the playground is the only place a
model is called from.

* **Another provider** (Anthropic, Google, …): set its key on the Phoenix
  container — `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` — in `.env`, and it becomes
  usable in the playground. Leave it unset and it stays unusable.
* **Another OpenAI-compatible endpoint** (a second vLLM, a second agent): store
  its key as a Phoenix secret in the UI, then give that model a custom base
  url. A key coming from the server environment is deliberately refused with a
  custom base url — it would leak that key to a client-supplied host — which is
  why the per-model route needs a stored secret rather than `.env`.
* **Another agent id from hiro**: hiro serves exactly one, named by
  `CHAT_AGENT_MODEL_NAME` in `hiro/.env`, which is both what it advertises and
  what it accepts. Change that and the playground model name changes with it.
