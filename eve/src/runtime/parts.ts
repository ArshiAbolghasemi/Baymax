/** Folds a stream of agent events into assistant-ui message parts.
 *
 * Pure accumulation, no I/O: the adapter feeds it events and re-reads the
 * whole content array after each one, which is the snapshot assistant-ui
 * expects a run to yield.
 */

import type { ToolCallMessagePart } from "@assistant-ui/react";

/** The JSON shape assistant-ui accepts for tool arguments. */
type Args = ToolCallMessagePart["args"];

import type { AgentEvent } from "../api/events";

type Part = { type: "text"; text: string } | ToolCallMessagePart;

/** A tool result is JSON from the MCP server. Parsed when it parses, so the
 *  renderer can show fields rather than one long escaped string. */
function parseResult(content: string): unknown {
  try {
    return JSON.parse(content);
  } catch {
    return content;
  }
}

export class PartsAccumulator {
  #parts: Part[] = [];

  get parts(): readonly Part[] {
    return this.#parts;
  }

  add(event: AgentEvent): void {
    switch (event.kind) {
      case "text":
        this.#appendText(event.text);
        break;
      case "tool-call":
        this.#openCall(event.id, event.name, event.argsText);
        break;
      case "tool-result":
        this.#closeCall(event.id, event.content);
        break;
    }
  }

  /** Text arrives token by token; keep it in one part so it renders as one
   *  paragraph rather than a part per token. A tool call ends the run of text,
   *  so anything after it starts a new part. */
  #appendText(text: string): void {
    const last = this.#parts.at(-1);
    if (last?.type === "text") {
      this.#parts[this.#parts.length - 1] = { type: "text", text: last.text + text };
      return;
    }
    this.#parts.push({ type: "text", text });
  }

  #openCall(toolCallId: string, toolName: string, argsText: string): void {
    let args: Args = {};
    try {
      args = JSON.parse(argsText) as Args;
    } catch {
      // Leave args empty; argsText is still shown, so nothing is hidden.
    }
    this.#parts.push({ type: "tool-call", toolCallId, toolName, argsText, args });
  }

  #closeCall(toolCallId: string, content: string): void {
    const index = this.#parts.findIndex(
      (part) => part.type === "tool-call" && part.toolCallId === toolCallId,
    );
    if (index === -1) return;
    const call = this.#parts[index] as ToolCallMessagePart;
    this.#parts[index] = { ...call, result: parseResult(content) };
  }
}
