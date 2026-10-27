import { describe, expect, it } from 'vitest';
import { type Checks, DEFAULT_LIMITS, admit, limitsFromEnv, statusFor } from './gatekeeper';

/** Checks with fixed answers, recording which ones ran (so order and side effects are visible). */
function checks(answers: { human?: boolean; live?: number; visitor?: number; daily?: number }) {
  const ran: string[] = [];
  const fake: Checks = {
    isHuman: async () => (ran.push('isHuman'), answers.human ?? true),
    liveCalls: async () => (ran.push('liveCalls'), answers.live ?? 0),
    countVisitorCall: async () => (ran.push('countVisitorCall'), answers.visitor ?? 1),
    countDailyCall: async () => (ran.push('countDailyCall'), answers.daily ?? 1),
  };
  return { fake, ran };
}

describe('admit', () => {
  it('lets a first call through after every check', async () => {
    const { fake, ran } = checks({});
    expect(await admit(DEFAULT_LIMITS, fake)).toEqual({ ok: true });
    expect(ran).toEqual(['isHuman', 'liveCalls', 'countVisitorCall', 'countDailyCall']);
  });

  it('refuses a failed bot check before touching any counter', async () => {
    const { fake, ran } = checks({ human: false });
    expect(await admit(DEFAULT_LIMITS, fake)).toEqual({ ok: false, reason: 'bot_check' });
    expect(ran).toEqual(['isHuman']);
  });

  it('turns callers away when the demo is full, without using up their hourly calls', async () => {
    const { fake, ran } = checks({ live: DEFAULT_LIMITS.maxLiveCalls });
    expect(await admit(DEFAULT_LIMITS, fake)).toEqual({ ok: false, reason: 'busy' });
    expect(ran).not.toContain('countVisitorCall');
  });

  it('takes one call at a time, since every call shares the free LLM tier', async () => {
    expect(DEFAULT_LIMITS.maxLiveCalls).toBe(1);
    expect(await admit(DEFAULT_LIMITS, checks({ live: 1 }).fake)).toEqual({
      ok: false,
      reason: 'busy',
    });
  });

  it('allows the hourly limit exactly, then refuses the next call', async () => {
    const limit = DEFAULT_LIMITS.callsPerVisitorPerHour;
    expect(await admit(DEFAULT_LIMITS, checks({ visitor: limit }).fake)).toEqual({ ok: true });
    const { fake, ran } = checks({ visitor: limit + 1 });
    expect(await admit(DEFAULT_LIMITS, fake)).toEqual({ ok: false, reason: 'rate_limited' });
    expect(ran).not.toContain('countDailyCall'); // a refused visitor doesn't use the daily cap
  });

  it('allows the daily cap exactly, then refuses the next call', async () => {
    const cap = DEFAULT_LIMITS.callsPerDay;
    expect(await admit(DEFAULT_LIMITS, checks({ daily: cap }).fake)).toEqual({ ok: true });
    expect(await admit(DEFAULT_LIMITS, checks({ daily: cap + 1 }).fake)).toEqual({
      ok: false,
      reason: 'daily_cap',
    });
  });
});

describe('limitsFromEnv', () => {
  it('reads positive whole numbers and falls back for anything else', () => {
    expect(
      limitsFromEnv({ CALLS_PER_VISITOR_PER_HOUR: '2', CALLS_PER_DAY: 'ten', MAX_LIVE_CALLS: '0' })
    ).toEqual({ ...DEFAULT_LIMITS, callsPerVisitorPerHour: 2 });
    expect(limitsFromEnv({})).toEqual(DEFAULT_LIMITS);
  });
});

describe('statusFor', () => {
  it('uses 403 for bots and 429 for every kind of "not now"', () => {
    expect(statusFor('bot_check')).toBe(403);
    expect(['busy', 'rate_limited', 'daily_cap'].map((r) => statusFor(r as never))).toEqual([
      429, 429, 429,
    ]);
  });
});
