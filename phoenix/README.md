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

Then create the prompts — a fresh Phoenix has none:

```bash
cd ../hiro
uv run python scripts/seed_prompts.py --tag production
```

That script holds Baymax's original wording and is the only place it exists in
the repository. From then on, edit prompts in Phoenix, not in the script.

## Usage

| | |
| --- | --- |
| `hiro-answer` | the persona and answering rules. Variables: `instructions`, `documents`, `history`, `question` |
| `hiro-guardrail` | the medical-topic classifier. Variable: `question` |
| `hiro-blocked` | sent verbatim when the guardrail rejects a question |
| `hiro-no-instructions` | stands in when no instruction matched |
| `hiro-no-documents` | stands in when retrieval found nothing |
| `hiro-no-history` | stands in on the first turn of a conversation |

Those names are configuration, not constants: the `CHAT_PROMPT_*` settings in
`hiro/.env` (defaults in `hiro/hiro/chat/config.py`), read by both the workflow
and the seeding script. Renaming a prompt in Phoenix means changing the
matching variable — otherwise the fetch looks for a name that is no longer
there.

Templates are **mustache**: `{{question}}`, not `{question}`.

Edit a prompt in the UI and it takes effect on hiro's next question — prompts
are fetched per turn, not cached. To review changes before they go live,
set `PHOENIX_PROMPT_TAG=production` in `hiro/.env`: hiro then reads only the
version carrying that tag, and a new version is ignored until you move the tag
to it.

Two rules the guardrail prompt cannot break, whatever you rewrite:

* It must instruct the model to reply with exactly one character, `1` or `0`.
  Anything else is read as `0`, which blocks every question.
* `hiro-blocked` is never generated. That is the point of it — a refusal that
  cannot be steered by the input.

## Notes worth knowing

**Prompts are versioned, never overwritten.** Re-running the seed script adds a
new version to each prompt, which quietly supersedes edits made in the UI when
no tag is pinned. Use `--only <identifier>` to reseed one.

**Auth is off by default.** Fine for a local bind, not for an exposed host. Set
`PHOENIX_ENABLE_AUTH=true` and `PHOENIX_SECRET`, then give hiro a
`PHOENIX_API_KEY`.

**Prompts are the assistant's behaviour.** Anyone who can reach this UI can
change what a medical assistant says, without review or deploy. That is the
feature; treat write access accordingly.
