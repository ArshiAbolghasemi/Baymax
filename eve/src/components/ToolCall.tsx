/** How a tool call looks while it runs, and once it has answered.
 *
 * Every tool hiro can call is a dobby MCP tool returning JSON, so one renderer
 * covers all of them: name, arguments, and the result — collapsed by default,
 * because a drug label is long and the answer below it is the point.
 */

import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { useState } from "react";

function pretty(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export const ToolCall: ToolCallMessagePartComponent = ({
  toolName,
  args,
  argsText,
  result,
  isError,
}) => {
  const [open, setOpen] = useState(false);
  const running = result === undefined;
  const summary = Object.entries(args ?? {})
    .map(([key, value]) => `${key}: ${pretty(value)}`)
    .join(", ");

  return (
    <div className={`tool ${running ? "tool-running" : isError ? "tool-error" : "tool-done"}`}>
      <button
        type="button"
        className="tool-header"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <span className="tool-status" aria-hidden>
          {running ? "◌" : isError ? "✕" : "✓"}
        </span>
        <span className="tool-name">{toolName}</span>
        <span className="tool-summary">{summary || argsText}</span>
        <span className="tool-chevron" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
      </button>

      {open && (
        <div className="tool-body">
          <div className="tool-label">arguments</div>
          <pre>{pretty(args && Object.keys(args).length ? args : argsText)}</pre>
          <div className="tool-label">{running ? "waiting for the tool…" : "result"}</div>
          {!running && <pre>{pretty(result)}</pre>}
        </div>
      )}
    </div>
  );
};
