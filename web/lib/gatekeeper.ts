/**
 * Who gets a call: the abuse and cost checks in front of the token endpoint (CLAUDE.md section 7).
 *
 * Every public call spends the same free quotas as Dev's testing (LiveKit's 5 concurrent sessions,
 * agent minutes, the $2.50 monthly LLM credit), so a token is only issued when all checks pass.
 * Pure logic with its I/O passed in, so it's tested without Cloudflare, Redis or LiveKit.
 *
 * Order matters:
 * 1. Bot check first, so bots never touch a counter.
 * 2. Live capacity next: being turned away because the demo is full shouldn't use up the
 *    visitor's calls for the hour.
 * 3. The visitor's hourly limit.
 * 4. The daily cap last, so only calls that are about to happen count against it.
 */

export type Refusal = 'bot_check' | 'busy' | 'rate_limited' | 'daily_cap';
export type Admission = { ok: true } | { ok: false; reason: Refusal };

export type Limits = {
  callsPerVisitorPerHour: number;
  callsPerDay: number;
  maxLiveCalls: number; // LiveKit Build allows 5 concurrent sessions; leave room for testing
};

export type Checks = {
  isHuman(): Promise<boolean>;
  liveCalls(): Promise<number>;
  /** Count this request against the visitor's hour; returns the count including it. */
  countVisitorCall(): Promise<number>;
  /** Count this request against today's total; returns the count including it. */
  countDailyCall(): Promise<number>;
};

export async function admit(limits: Limits, checks: Checks): Promise<Admission> {
  if (!(await checks.isHuman())) return { ok: false, reason: 'bot_check' };
  if ((await checks.liveCalls()) >= limits.maxLiveCalls) return { ok: false, reason: 'busy' };
  if ((await checks.countVisitorCall()) > limits.callsPerVisitorPerHour) {
    return { ok: false, reason: 'rate_limited' };
  }
  if ((await checks.countDailyCall()) > limits.callsPerDay)
    return { ok: false, reason: 'daily_cap' };
  return { ok: true };
}

export const DEFAULT_LIMITS: Limits = {
  callsPerVisitorPerHour: 3,
  callsPerDay: 5,
  maxLiveCalls: 4,
};

/** Limits from the environment, falling back to the defaults for anything unset or invalid. */
export function limitsFromEnv(env: Record<string, string | undefined>): Limits {
  const read = (name: string, fallback: number) => {
    const value = Number(env[name]);
    return Number.isInteger(value) && value > 0 ? value : fallback;
  };
  return {
    callsPerVisitorPerHour: read(
      'CALLS_PER_VISITOR_PER_HOUR',
      DEFAULT_LIMITS.callsPerVisitorPerHour
    ),
    callsPerDay: read('CALLS_PER_DAY', DEFAULT_LIMITS.callsPerDay),
    maxLiveCalls: read('MAX_LIVE_CALLS', DEFAULT_LIMITS.maxLiveCalls),
  };
}

/** HTTP status for a refusal: 403 for a failed bot check, 429 for every kind of "not now". */
export function statusFor(reason: Refusal): number {
  return reason === 'bot_check' ? 403 : 429;
}
