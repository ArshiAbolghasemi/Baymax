/** The conversation this tab is in.
 *
 * hiro's completions name a conversation and never create one, so one is
 * opened here — once — before the first question. sessionStorage keeps it
 * across a reload but not across tabs, which matches what a person expects
 * from a chat window.
 */

import { config } from "../config.ts";

const KEY = "eve.session-uid";

function cached(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null; // Private mode, or storage disabled.
  }
}

function remember(uid: string): void {
  try {
    sessionStorage.setItem(KEY, uid);
  } catch {
    // Not being able to remember it costs history on reload, nothing more.
  }
}

async function open(): Promise<string> {
  const response = await fetch(`${config.baseUrl}/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${config.apiKey}`,
    },
    body: JSON.stringify({}),
  });
  if (!response.ok) {
    throw new Error(`could not open a session: hiro answered ${response.status}`);
  }
  const { session_uid } = (await response.json()) as { session_uid: string };
  remember(session_uid);
  return session_uid;
}

/** The current conversation, opening one if this tab has none. */
export async function sessionUid(): Promise<string> {
  return cached() ?? (await open());
}

/** Forget the conversation, so the next question opens a fresh one.
 *  Used when the server says the remembered one no longer exists. */
export function forgetSession(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // Nothing to forget.
  }
}
