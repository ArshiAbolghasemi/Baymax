/** One conversation id per tab.
 *
 * hiro keys history off `X-Session-UID`; without it every turn would look like
 * a first question. sessionStorage keeps the thread across a reload but not
 * across tabs, which matches what a person expects from a chat window.
 */

const KEY = "eve.session-uid";

export function sessionUid(): string {
  try {
    const existing = sessionStorage.getItem(KEY);
    if (existing) return existing;
    const created = crypto.randomUUID();
    sessionStorage.setItem(KEY, created);
    return created;
  } catch {
    // Private mode, or storage disabled: a per-load id still beats none.
    return crypto.randomUUID();
  }
}
