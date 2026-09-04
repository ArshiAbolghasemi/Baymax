/** One check for the two modules with real logic: the wire decoder and the
 *  parts accumulator. The frames below are verbatim output from hiro's
 *  `_chunk`/`_delta`, so this fails if either side of the contract moves.
 *
 *      npm run check
 */

import assert from "node:assert/strict";
import { decodeChunk } from "./api/events.ts";
import { PartsAccumulator } from "./runtime/parts.ts";

const FRAMES = [
  '{"id":"c","object":"chat.completion.chunk","created":0,"model":"baymax","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}',
  '{"id":"c","object":"chat.completion.chunk","created":0,"model":"baymax","choices":[{"index":0,"delta":{"content":"Let me check the label. "},"finish_reason":null}]}',
  '{"id":"c","object":"chat.completion.chunk","created":0,"model":"baymax","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"search_drug_label","arguments":"{\\"drug_name\\":\\"ibuprofen\\",\\"section\\":\\"warnings\\"}"}}]},"finish_reason":null}]}',
  '{"id":"c","object":"chat.completion.chunk","created":0,"model":"baymax","choices":[{"index":0,"delta":{"tool_results":[{"tool_call_id":"call_1","name":"search_drug_label","content":"{\\"status\\":\\"ok\\",\\"sections\\":{\\"warnings\\":\\"Do not use if...\\"}}"}]},"finish_reason":null}]}',
  '{"id":"c","object":"chat.completion.chunk","created":0,"model":"baymax","choices":[{"index":0,"delta":{"content":"The label warns "},"finish_reason":null}]}',
  '{"id":"c","object":"chat.completion.chunk","created":0,"model":"baymax","choices":[{"index":0,"delta":{"content":"about stomach bleeding."},"finish_reason":null}]}',
  '{"id":"c","object":"chat.completion.chunk","created":0,"model":"baymax","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}',
];

const parts = new PartsAccumulator();
for (const frame of FRAMES) {
  for (const event of decodeChunk(JSON.parse(frame))) parts.add(event);
}
const result = [...parts.parts];

assert.equal(result.length, 3, "text, one tool call, text");
assert.deepEqual(result[0], { type: "text", text: "Let me check the label. " });

const call = result[1];
assert.equal(call.type, "tool-call");
assert.equal(call.toolName, "search_drug_label");
assert.deepEqual(call.args, { drug_name: "ibuprofen", section: "warnings" });
assert.equal(call.result.sections.warnings, "Do not use if...", "result parsed onto its call");

assert.equal(
  result[2].text,
  "The label warns about stomach bleeding.",
  "tokens after a tool call coalesce into one part",
);

// A failed retrieval is a result, not an error: it must still land on the call.
const orphan = new PartsAccumulator();
orphan.add({ kind: "tool-result", id: "missing", name: "x", content: "{}" });
assert.equal(orphan.parts.length, 0, "a result for an unknown call is dropped, not crashed on");

console.log("ok — hiro frames render as assistant-ui parts");
