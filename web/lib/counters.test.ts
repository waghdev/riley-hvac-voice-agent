import { describe, expect, it } from 'vitest';
import { counterFromEnv, dayKey, memoryCounter, visitorKey } from './counters';

const at = (iso: string) => new Date(iso);

describe('window keys', () => {
  it('give each visitor one key per UTC hour, and the day one key per UTC day', () => {
    const k1 = visitorKey('203.0.113.7', 'secret', at('2026-10-25T14:05:00Z'));
    const k2 = visitorKey('203.0.113.7', 'secret', at('2026-10-25T14:59:59Z'));
    const k3 = visitorKey('203.0.113.7', 'secret', at('2026-10-25T15:00:00Z'));
    expect(k1).toBe(k2);
    expect(k3).not.toBe(k1);
    expect(k1.endsWith(':2026-10-25T14')).toBe(true);
    expect(dayKey(at('2026-10-25T23:59:59Z'))).toBe('riley:day:2026-10-25');
  });

  it('never store the IP itself, and tell visitors apart', () => {
    const now = at('2026-10-25T14:00:00Z');
    const key = visitorKey('203.0.113.7', 'secret', now);
    expect(key).not.toContain('203.0.113.7');
    expect(visitorKey('203.0.113.8', 'secret', now)).not.toBe(key);
  });
});

describe('counters', () => {
  it('count up per key', async () => {
    const counter = memoryCounter();
    expect(await counter.increment('a', 60)).toBe(1);
    expect(await counter.increment('a', 60)).toBe(2);
    expect(await counter.increment('b', 60)).toBe(1);
  });

  it('use Upstash only when both its URL and token are set', () => {
    expect(counterFromEnv({})).toBeNull();
    expect(counterFromEnv({ KV_REST_API_URL: 'https://x.upstash.io' })).toBeNull();
    expect(
      counterFromEnv({ KV_REST_API_URL: 'https://x.upstash.io', KV_REST_API_TOKEN: 't' })
    ).not.toBeNull();
  });
});
