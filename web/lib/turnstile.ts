/**
 * Cloudflare Turnstile: the server-side half of the bot check. The page's widget gives the
 * browser a single-use token; only Cloudflare can say whether it's valid, so the token endpoint
 * asks before issuing a LiveKit token.
 */

const VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify';

// Cloudflare's published test keys: they always pass. Used only in local development, so the
// page works before real keys exist (https://developers.cloudflare.com/turnstile/troubleshooting/testing/).
export const TEST_SITE_KEY = '1x00000000000000000000AA';
export const TEST_SECRET_KEY = '1x0000000000000000000000000000000AA';

export async function verifyTurnstile(
  token: unknown,
  ip: string | undefined,
  secret: string,
  fetchFn: typeof fetch = fetch
): Promise<boolean> {
  if (typeof token !== 'string' || token.length === 0 || token.length > 2048) return false;
  const body = new URLSearchParams({ secret, response: token });
  if (ip) body.set('remoteip', ip);
  try {
    const res = await fetchFn(VERIFY_URL, {
      method: 'POST',
      body,
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return false;
    const data = (await res.json()) as { success?: unknown };
    return data.success === true;
  } catch {
    return false; // can't verify, so don't admit: fail closed
  }
}
