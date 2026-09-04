# eve

A chat UI for the hiro agent, built on [assistant-ui](https://www.assistant-ui.com/).
Its reason to exist is the middle of an answer: every tool hiro calls appears
as its own card — name, arguments, and the JSON the MCP server returned —
while the reply streams around it.

Like `bashmax`, it is a pure client: no database, no model, no credentials. It
talks to one endpoint.

## Requirements

A running hiro API (`../hiro/entrypoints/api.sh`), and therefore everything
hiro needs. Node 20+.

## Setup

```bash
cp .env.example .env      # only needed if hiro is not on localhost:8080
npm install
npm run dev               # http://localhost:5173
```

| | |
| --- | --- |
| `npm run dev` | serve on :5173 with hot reload |
| `npm run lint` | Biome: lint + format check |
| `npm run lint:fix` | apply every safe fix |
| `npm run typecheck` | `tsc --noEmit`, strict |
| `npm run check` | the one test, described below |
| `npm run build` | lint, typecheck, then bundle into `dist/` |

`npm run build` runs the first two for you, so CI needs only that plus
`npm run check`.

## How it fits together

Each module does one thing, and they only depend downwards:

| | |
| --- | --- |
| `config.ts` | where hiro is, which model, what key |
| `api/events.ts` | hiro's wire format → typed `AgentEvent`s |
| `api/stream.ts` | the POST and its SSE framing; knows nothing about meaning |
| `api/messages.ts` | assistant-ui messages → the wire shape hiro expects |
| `api/session.ts` | one conversation id per tab |
| `runtime/parts.ts` | folds events into assistant-ui message parts |
| `runtime/adapter.ts` | the one place assistant-ui and hiro meet |
| `components/ToolCall.tsx` | how a tool call looks, running and finished |
| `components/Thread.tsx` | messages, parts, composer |

## Notes worth knowing

**Tool results are not standard OpenAI.** Text and tool *calls* use the normal
delta fields, so any OpenAI client still reads the reply. Results have no
standard shape — OpenAI expects the client to run the tools, whereas hiro runs
them itself — so they arrive under `tool_results`, and clients that do not know
the field ignore it. `api/events.ts` is the only file that knows this.

**One text part per run of tokens.** A tool call ends the current run, so the
sentence before a lookup and the sentence after it are separate parts, in the
order they happened. That is what makes the transcript read as a sequence of
events rather than a wall of text with cards bolted on.

**A tool result is JSON, and is parsed for display.** If it does not parse it
is shown verbatim rather than dropped — the MCP server returns
`status: ok | no_results | error`, and an `error` result is still information
the reader wants.

**The session lives in `sessionStorage`.** hiro keys history off
`X-Session-UID`; a reload keeps the thread, a new tab starts a fresh one.

**Only `baymax` is served.** hiro refuses any other model with a 404, so
`VITE_HIRO_MODEL` exists to follow a renamed `CHAT_AGENT_MODEL_NAME`, not to
pick a different model.

## Lint

[Biome](https://biomejs.dev) — one dev dependency doing both linting and
formatting, which is why it is here instead of ESLint plus a formatter plus
their plugins. Config is `biome.json`: the recommended rule preset, 2-space
indent, 96 columns.

```bash
npm run lint        # check
npm run lint:fix    # apply safe fixes
```

It is the counterpart of `ruff` in hiro and `golangci-lint` in dobby.

## The one test

```bash
npm run check
```

`src/check.mjs` replays SSE frames captured verbatim from hiro's own encoder
through the decoder and the accumulator, and asserts the parts that come out —
including that a result for an unknown call is dropped rather than thrown on.
It fails if either side of the wire contract moves. No framework: Node runs the
TypeScript directly.
