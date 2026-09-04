/** The conversation: messages, their parts, and the composer. */

import { ComposerPrimitive, MessagePrimitive, ThreadPrimitive } from "@assistant-ui/react";
import { ToolCall } from "./ToolCall";

const UserMessage = () => (
  <MessagePrimitive.Root className="message message-user">
    <MessagePrimitive.Parts />
  </MessagePrimitive.Root>
);

const AssistantMessage = () => (
  <MessagePrimitive.Root className="message message-assistant">
    <MessagePrimitive.Parts components={{ tools: { Fallback: ToolCall } }} />
  </MessagePrimitive.Root>
);

export const Thread = () => (
  <ThreadPrimitive.Root className="thread">
    <ThreadPrimitive.Viewport className="thread-viewport">
      <ThreadPrimitive.Empty>
        <p className="thread-empty">Ask about a symptom, a medication, or a condition.</p>
      </ThreadPrimitive.Empty>

      <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
    </ThreadPrimitive.Viewport>

    <ComposerPrimitive.Root className="composer">
      <ComposerPrimitive.Input className="composer-input" placeholder="Ask Baymax…" autoFocus />
      <ComposerPrimitive.Send className="composer-send">Send</ComposerPrimitive.Send>
    </ComposerPrimitive.Root>
  </ThreadPrimitive.Root>
);
