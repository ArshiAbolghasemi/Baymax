# bashmax

A small interactive terminal client for Hiro's OpenAI-compatible Baymax chat
API. It opens a server-side conversation, streams the answer as it arrives, and
renders Markdown with Rich.

Bashmax is only a client. It does not import Hiro, connect to its database, or
need model credentials.

## Requirements

- Python 3.14 or newer
- [uv](https://docs.astral.sh/uv/)
- A running Hiro API

## Setup

```bash
cp .env.example .env
uv sync
```

The defaults connect to Hiro at `http://localhost:8080/v1` and request its
default `baymax` model.

## Run

```bash
./entrypoints/chat.sh
```

You can override settings for one run:

```bash
./entrypoints/chat.sh \
  --url http://localhost:8080/v1 \
  --model baymax \
  --user alice
```

Run `./entrypoints/chat.sh --help` for every option.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `BAYMAX_URL` | `http://localhost:8080/v1` | Hiro API base URL, including `/v1`. |
| `BAYMAX_MODEL` | `baymax` | Model name sent to `/chat/completions`. |
| `BAYMAX_API_KEY` | `not-needed` | Bearer token sent with requests. |
| `USE_UV` | `auto` | Set to `false` to run with the current Python environment instead of `uv run`. |

Command-line arguments override environment values:

| Argument | Purpose |
| --- | --- |
| `--url URL` | Override the Hiro API base URL. |
| `--model NAME` | Override the requested model. |
| `--api-key TOKEN` | Override the bearer token. |
| `--session UUID` | Resume an existing Hiro session. |
| `--user ID` | Send a stable user identifier with every request. |
| `--timeout SECONDS` | Override the response timeout. |
| `--raw` | Print replies without Markdown rendering. |

## Conversation commands

| Command | Action |
| --- | --- |
| `/new` | Open a new server session and clear the local transcript. |
| `/session` | Show the current session UUID. |
| `/models` | List the models advertised by Hiro. |
| `/raw` | Toggle Markdown rendering. |
| `/clear` | Clear the terminal. |
| `/help` | Show command help. |
| `/quit`, `/exit`, `/q` | Exit. Ctrl-D and Ctrl-C also exit. |

## Session behavior

Before the first question, Bashmax calls `POST /v1/sessions` and stores the
returned session UUID. Every completion sends that UUID to
`POST /v1/chat/completions`, allowing Hiro to persist conversation history and
group Phoenix traces under the same session.

The local transcript is also replayed with each request for OpenAI-compatible
client behavior. `/new` starts a separate conversation; `--session UUID`
resumes one that already exists on the server.

## Streaming

Bashmax requests `stream: true` and consumes Hiro's server-sent events. It
renders `choices[0].delta.content` incrementally, displays time to first token
and total response time, and reports API or mid-stream errors without adding a
failed turn to the local transcript.

## Troubleshooting

**Could not open a session.** Confirm Hiro is running and `BAYMAX_URL` includes
the `/v1` suffix:

```bash
curl -s http://localhost:8080/v1/models
```

**HTTP 404 for the model.** Set `BAYMAX_MODEL` to a model returned by
`GET /v1/models` or use `/models` inside Bashmax.

**Existing session is rejected.** The UUID must already exist in Hiro and must
belong to the same `--user` identity used when it was created. Start with
`/new` if the previous session should not be reused.

**Markdown looks wrong.** Use `--raw` or `/raw` to display the response
verbatim.

## Checks

```bash
uv run ruff check cli
uv run ruff format --check cli
```
