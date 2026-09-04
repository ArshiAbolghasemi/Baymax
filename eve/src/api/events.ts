/** hiro's stream, as types — and one decoder from its wire format to them.
 *
 * hiro sends OpenAI `chat.completion.chunk` frames. Text and tool calls use the
 * standard delta fields; tool *results* have no standard shape, because OpenAI
 * expects the client to run the tools, so they arrive under `tool_results`.
 */

export type AgentEvent =
  | { kind: "text"; text: string }
  | { kind: "tool-call"; id: string; name: string; argsText: string }
  | { kind: "tool-result"; id: string; name: string; content: string };

type WireDelta = {
  content?: string | null;
  tool_calls?: {
    id?: string;
    function?: { name?: string; arguments?: string };
  }[];
  tool_results?: { tool_call_id?: string; name?: string; content?: string }[];
};

type WireChunk = {
  choices?: { delta?: WireDelta }[];
  error?: { message?: string };
};

/** Everything one chunk carries. A chunk may hold nothing — the opening role
 *  frame and the closing finish_reason frame both have an empty delta. */
export function decodeChunk(raw: unknown): AgentEvent[] {
  const chunk = raw as WireChunk;
  if (chunk.error) throw new Error(chunk.error.message ?? "The agent failed.");

  const delta = chunk.choices?.[0]?.delta;
  if (!delta) return [];

  const events: AgentEvent[] = [];
  if (delta.content) {
    events.push({ kind: "text", text: delta.content });
  }
  for (const call of delta.tool_calls ?? []) {
    events.push({
      kind: "tool-call",
      id: call.id ?? "",
      name: call.function?.name ?? "unknown",
      argsText: call.function?.arguments ?? "{}",
    });
  }
  for (const result of delta.tool_results ?? []) {
    events.push({
      kind: "tool-result",
      id: result.tool_call_id ?? "",
      name: result.name ?? "unknown",
      content: result.content ?? "",
    });
  }
  return events;
}
