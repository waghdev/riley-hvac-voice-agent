/**
 * Call counters for the rate limits: per visitor per hour, and in total per day.
 *
 * Fixed windows keyed by the clock: "visitor X in hour 2026-10-25T14" and "day 2026-10-25"
 * (UTC). Each window is its own key, so a count can never leak into the next window even if a
 * key's expiry were lost; the expiry only cleans up. Counts live in Upstash Redis (free tier) in
 * production; a serverless function has no memory between requests.
 *
 * Visitors are counted by a keyed hash of their IP, never the IP itself (CLAUDE.md rule 3: no
 * real personal data stored).
 */
import { createHmac } from 'node:crypto';
import { Redis } from '@upstash/redis';

export interface Counter {
  /** Add one to `key` and return the new count. */
  increment(key: string, ttlSeconds: number): Promise<number>;
}

export function redisCounter(redis: Redis): Counter {
  return {
    async increment(key, ttlSeconds) {
      // One round trip: increment, then (re)set the cleanup expiry.
      const [count] = await redis
        .pipeline()
        .incr(key)
        .expire(key, ttlSeconds)
        .exec<[number, number]>();
      return count;
    },
  };
}

/** Local development only: counts reset whenever the dev server restarts. */
export function memoryCounter(): Counter {
  const counts = new Map<string, number>();
  return {
    async increment(key) {
      const count = (counts.get(key) ?? 0) + 1;
      counts.set(key, count);
      return count;
    },
  };
}

/** Upstash from the environment (its own variable names or the ones Vercel's integration sets). */
export function counterFromEnv(env: Record<string, string | undefined>): Counter | null {
  const url = env.UPSTASH_REDIS_REST_URL ?? env.KV_REST_API_URL;
  const token = env.UPSTASH_REDIS_REST_TOKEN ?? env.KV_REST_API_TOKEN;
  return url && token ? redisCounter(new Redis({ url, token })) : null;
}

export const HOUR = 60 * 60;
export const DAY = 24 * HOUR;

export function visitorKey(ip: string, secret: string, now: Date): string {
  const visitor = createHmac('sha256', secret).update(`visitor:${ip}`).digest('hex').slice(0, 16);
  return `riley:visitor:${visitor}:${now.toISOString().slice(0, 13)}`; // ...:2026-10-25T14
}

export function dayKey(now: Date): string {
  return `riley:day:${now.toISOString().slice(0, 10)}`; // riley:day:2026-10-25
}
