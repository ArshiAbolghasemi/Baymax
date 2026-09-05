/** The HTTP call and its SSE framing. Knows nothing about what the events mean. */

import { config } from "../config.ts";
import { type AgentEvent, decodeChunk } from "./events.ts";
import type { WireMessage } from "./messages.ts";
import { forgetSession, sessionUid } from "./session.ts";

const DONE = "[DONE]";

async function* lines(body: ReadableStream<Uint8Array>): AsyncGenerator<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE frames are separated by a blank line; a frame we care about is one
    // `data:` line, so splitting on newlines and ignoring the rest is enough.
    const parts = buffer.split("\n");
    buffer = parts.pop() ?? "";
    for (const line of parts) yield line;
  }
  if (buffer) yield buffer;
}

async function post(messages: WireMessage[], abortSignal: AbortSignal): Promise<Response> {
  return fetch(`${config.baseUrl}/chat/completions`, {
    method: "POST",
    signal: abortSignal,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${config.apiKey}`,
      "X-Session-UID": await sessionUid(),
    },
    body: JSON.stringify({ model: config.model, messages, stream: true }),
  });
}

/** Did hiro reject this because the conversation is gone? A restarted or wiped
 *  server leaves a remembered uid pointing at nothing; every other 404 (an
 *  unknown model, say) is a real error and must not be retried. */
async function sessionExpired(response: Response): Promise<boolean> {
  if (response.status !== 404) return false;
  const body = (await response.clone().json()) as { detail?: { code?: string } };
  return body.detail?.code === "session_not_found";
}

export async function* streamAgent(
  messages: WireMessage[],
  abortSignal: AbortSignal,
): AsyncGenerator<AgentEvent> {
  let response = await post(messages, abortSignal);

  if (await sessionExpired(response)) {
    forgetSession();
    response = await post(messages, abortSignal);
  }

  if (!response.ok || !response.body) {
    const detail = await response.text().catch(() => "");
    throw new Error(`hiro answered ${response.status}. ${detail}`.trim());
  }

  for await (const line of lines(response.body)) {
    if (!line.startsWith("data:")) continue;
    const payload = line.slice(5).trim();
    if (payload === DONE) return;
    if (!payload) continue;
    yield* decodeChunk(JSON.parse(payload));
  }
}
