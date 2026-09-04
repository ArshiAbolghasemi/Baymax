/** The HTTP call and its SSE framing. Knows nothing about what the events mean. */

import { config } from "../config";
import { type AgentEvent, decodeChunk } from "./events";
import type { WireMessage } from "./messages";
import { sessionUid } from "./session";

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

export async function* streamAgent(
  messages: WireMessage[],
  abortSignal: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const response = await fetch(`${config.baseUrl}/chat/completions`, {
    method: "POST",
    signal: abortSignal,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${config.apiKey}`,
      "X-Session-UID": sessionUid(),
    },
    body: JSON.stringify({ model: config.model, messages, stream: true }),
  });

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
