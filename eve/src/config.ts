/** Where the agent lives. Read once, at module load. */

// `?? {}` so the module also loads outside Vite — the check script runs it in Node.
const env = import.meta.env ?? {};

export const config = {
  /** hiro's OpenAI-compatible base url, including /v1. */
  baseUrl: (env.VITE_HIRO_URL ?? "http://localhost:8080/v1").replace(/\/$/, ""),
  /** The only model hiro serves; it refuses any other with 404. */
  model: env.VITE_HIRO_MODEL ?? "baymax",
  /** Sent as a bearer token. hiro does not check it today. */
  apiKey: env.VITE_HIRO_API_KEY ?? "not-needed",
} as const;
