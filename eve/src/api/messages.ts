/** assistant-ui messages → the wire shape hiro expects.
 *
 * Only text survives: hiro reads the last user message as the question and
 * supplies its own prompt, so tool parts from earlier turns would be dropped
 * on arrival anyway.
 */

import type { ThreadMessage } from "@assistant-ui/react";

export type WireMessage = { role: "user" | "assistant"; content: string };

function text(message: ThreadMessage): string {
  return message.content
    .map((part) => (part.type === "text" ? part.text : ""))
    .join("")
    .trim();
}

export function toWireMessages(messages: readonly ThreadMessage[]): WireMessage[] {
  return messages
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message) => ({ role: message.role as "user" | "assistant", content: text(message) }))
    .filter((message) => message.content.length > 0);
}
