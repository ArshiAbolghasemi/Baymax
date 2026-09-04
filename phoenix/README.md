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
