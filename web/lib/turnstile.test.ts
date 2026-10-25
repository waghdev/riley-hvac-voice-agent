import { describe, expect, it } from 'vitest';
import { verifyTurnstile } from './turnstile';

function cloudflare(answer: unknown, status = 200) {
  const sent: URLSearchParams[] = [];
  const fetchFn = (async (_url: string, init: RequestInit) => {
    sent.push(init.body as URLSearchParams);
    return new Response(JSON.stringify(answer), { status });
  }) as unknown as typeof fetch;
  return { fetchFn, sent };
}

describe('verifyTurnstile', () => {
  it('passes only when Cloudflare says success, and sends the secret, token and IP', async () => {
    const { fetchFn, sent } = cloudflare({ success: true });
    expect(await verifyTurnstile('tok', '203.0.113.7', 'shh', fetchFn)).toBe(true);
    expect(Object.fromEntries(sent[0])).toEqual({
      secret: 'shh',
      response: 'tok',
      remoteip: '203.0.113.7',
    });
  });

  it('fails without asking Cloudflare when there is no usable token', async () => {
    const { fetchFn, sent } = cloudflare({ success: true });
    for (const token of [undefined, '', 42, 'x'.repeat(2049)]) {
      expect(await verifyTurnstile(token, '203.0.113.7', 'shh', fetchFn)).toBe(false);
    }
    expect(sent).toHaveLength(0);
  });

  it('fails closed on a rejection, an error status or a network failure', async () => {
    expect(
      await verifyTurnstile('tok', undefined, 'shh', cloudflare({ success: false }).fetchFn)
    ).toBe(false);
    expect(await verifyTurnstile('tok', undefined, 'shh', cloudflare({}, 500).fetchFn)).toBe(false);
    const down = (async () => {
      throw new TypeError('fetch failed');
    }) as unknown as typeof fetch;
    expect(await verifyTurnstile('tok', undefined, 'shh', down)).toBe(false);
  });
});
