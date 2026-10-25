import { describe, expect, it, vi } from 'vitest';
import { CallRefused, createCallTokenSource } from './call-token-source';

function setup(response: { status: number; body: unknown } = { status: 201, body: {} }) {
  const fetchFn = vi.fn<typeof fetch>(
    async () => new Response(JSON.stringify(response.body), { status: response.status })
  );
  const onTurnstileSpent = vi.fn();
  const source = createCallTokenSource({
    turnstileToken: () => 'turnstile-token',
    onTurnstileSpent,
    fetchFn,
  });
  return { source, fetchFn, onTurnstileSpent };
}

/** Whether a promise has settled after the event loop has had a chance to run. */
async function settled(promise: Promise<unknown>): Promise<boolean> {
  let done = false;
  promise.then(
    () => (done = true),
    () => (done = true)
  );
  await new Promise((r) => setTimeout(r, 20));
  return done;
}

describe('createCallTokenSource', () => {
  it("ignores the session hook's own fetches: no request, no Turnstile token spent", async () => {
    // Bug (live page, 2026-10-25): the hook's warm-up fetch on page load was refused and showed
    // "We couldn't confirm you're human" before the visitor pressed Call.
    const { source, fetchFn, onTurnstileSpent } = setup();
    expect(await settled(source.fetch())).toBe(false);
    expect(fetchFn).not.toHaveBeenCalled();
    expect(onTurnstileSpent).not.toHaveBeenCalled();
  });

  it('makes exactly one request per press of the Call button', async () => {
    const { source, fetchFn, onTurnstileSpent } = setup({
      status: 201,
      body: { server_url: 'wss://lk.example', participant_token: 'jwt' },
    });
    source.request();
    expect(await source.fetch()).toEqual({
      serverUrl: 'wss://lk.example',
      participantToken: 'jwt',
    });
    expect(fetchFn).toHaveBeenCalledOnce();
    const [, init] = fetchFn.mock.calls[0]!;
    expect(JSON.parse(init!.body as string)).toEqual({
      turnstile_token: 'turnstile-token',
    });
    expect(onTurnstileSpent).toHaveBeenCalledOnce();
    expect(await settled(source.fetch())).toBe(false); // the hook's prefetch after the call
    expect(fetchFn).toHaveBeenCalledOnce();
  });

  it('turns a refusal into CallRefused with its reason', async () => {
    const { source } = setup({ status: 429, body: { error: 'daily_cap' } });
    source.request();
    await expect(source.fetch()).rejects.toEqual(new CallRefused('daily_cap'));
  });

  it('forgets a request that was cancelled', async () => {
    const { source, fetchFn } = setup();
    source.request();
    source.cancel();
    expect(await settled(source.fetch())).toBe(false);
    expect(fetchFn).not.toHaveBeenCalled();
  });
});
