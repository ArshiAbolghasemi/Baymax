/** The one place assistant-ui and hiro meet. */

import type { ChatModelAdapter } from "@assistant-ui/react";
import { toWireMessages } from "../api/messages.ts";
import { streamAgent } from "../api/stream.ts";
import { PartsAccumulator } from "./parts.ts";

export const hiroAdapter: ChatModelAdapter = {
  async *run({ messages, abortSignal }) {
    const parts = new PartsAccumulator();

    for await (const event of streamAgent(toWireMessages(messages), abortSignal)) {
      parts.add(event);
      yield { content: [...parts.parts], status: { type: "running" } };
    }

    yield { content: [...parts.parts], status: { type: "complete", reason: "stop" } };
  },
};
