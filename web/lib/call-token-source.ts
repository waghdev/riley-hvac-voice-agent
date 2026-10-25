/**
 * Where the page gets a LiveKit token: POST /api/token with the visitor's Turnstile token, only
 * when the visitor pressed Call.
 *
 * useSession also fetches tokens on its own: once on mount (to warm up the connection) and again
 * when a call ends (to have the next one ready). Those requests carried no Turnstile token, were
 * refused, and showed "We couldn't confirm you're human" before anyone pressed Call; they also
 * spent the visitor's Turnstile token (Dev's first visit to the live page, 2026-10-25). So a
 * fetch nobody asked for never settles: the hook doesn't wait on those, so nothing hangs, and
 * nothing reaches the endpoint.
 *
 * A fresh request every time, no caching: a cached token (TokenSource.custom/endpoint keep one)
 * could rejoin a deleted room, recreating it and dispatching Riley without passing the checks.
 */

export type CallCredentials = { serverUrl: string; participantToken: string };

/** /api/token said no; `code` is its refusal reason (lib/gatekeeper.ts). */
export class CallRefused extends Error {
  constructor(readonly code: string) {
    super(`call refused: ${code}`);
  }
}

export interface CallTokenSourceOptions {
  /** The visitor's Turnstile token, if they have one. */
  turnstileToken(): string | null;
  /** Called the moment the Turnstile token is used: it's single-use, whatever the answer. */
  onTurnstileSpent(): void;
  fetchFn?: typeof fetch;
}

export function createCallTokenSource({
  turnstileToken,
  onTurnstileSpent,
  fetchFn = (...args) => fetch(...args),
}: CallTokenSourceOptions) {
  let requested = false;
  const never = new Promise<never>(() => {});

  return {
    /** The Call button: allow exactly one token request. */
    request() {
      requested = true;
    },
    /** After the call starts or fails: anything later is the hook's own, and stays local. */
    cancel() {
      requested = false;
    },
    /** For TokenSource.literal. */
    async fetch(): Promise<CallCredentials> {
      if (!requested) return never;
      requested = false;
      const token = turnstileToken();
      onTurnstileSpent();
      const res = await fetchFn('/api/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ turnstile_token: token }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new CallRefused(String(data.error ?? 'unavailable'));
      return { serverUrl: data.server_url, participantToken: data.participant_token };
    },
  };
}
