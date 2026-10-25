/**
 * POST /api/token: a LiveKit token for one call with Riley, if the gatekeeper admits it.
 *
 * Server-side only: the LiveKit API secret, the Turnstile secret and the Redis token never reach
 * the browser. Request body: { turnstile_token }. Responses follow LiveKit's standard token
 * endpoint format ({ server_url, participant_token }, 201), or { error } with 403/429 (refused)
 * or 503 (not configured, or a dependency is down: fail closed, since every call costs quota).
 */
import { type NextRequest, NextResponse } from 'next/server';
import { type LiveKitConfig, callToken, liveCalls } from '@/lib/calls';
import {
  type Counter,
  DAY,
  HOUR,
  counterFromEnv,
  dayKey,
  memoryCounter,
  visitorKey,
} from '@/lib/counters';
import { admit, limitsFromEnv, statusFor } from '@/lib/gatekeeper';
import { TEST_SECRET_KEY, verifyTurnstile } from '@/lib/turnstile';

export const dynamic = 'force-dynamic'; // never cached

const IN_DEVELOPMENT = process.env.NODE_ENV === 'development';
// Local development may run without Upstash; one in-memory counter per dev server.
let devCounter: Counter | null = null;

type Config = { livekit: LiveKitConfig; turnstileSecret: string; counter: Counter };

function readConfig(env: Record<string, string | undefined>): Config | { missing: string[] } {
  const missing = ['LIVEKIT_URL', 'LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET'].filter((n) => !env[n]);
  let turnstileSecret = env.TURNSTILE_SECRET_KEY;
  if (!turnstileSecret && IN_DEVELOPMENT) turnstileSecret = TEST_SECRET_KEY;
  if (!turnstileSecret) missing.push('TURNSTILE_SECRET_KEY');
  let counter = counterFromEnv(env);
  if (!counter && IN_DEVELOPMENT) counter = devCounter ??= memoryCounter();
  if (!counter) missing.push('UPSTASH_REDIS_REST_URL/TOKEN (or KV_REST_API_URL/TOKEN)');
  if (missing.length > 0 || !turnstileSecret || !counter) return { missing };
  return {
    livekit: {
      url: env.LIVEKIT_URL!,
      apiKey: env.LIVEKIT_API_KEY!,
      apiSecret: env.LIVEKIT_API_SECRET!,
      agentName: env.AGENT_NAME || 'riley',
    },
    turnstileSecret,
    counter,
  };
}

/** The caller's IP as Vercel reports it (the first address in x-forwarded-for). */
function clientIp(req: NextRequest): string {
  const forwarded = req.headers.get('x-forwarded-for')?.split(',')[0]?.trim();
  return forwarded || req.headers.get('x-real-ip') || 'unknown';
}

function reply(body: object, status: number) {
  return NextResponse.json(body, { status, headers: { 'Cache-Control': 'no-store' } });
}

export async function POST(req: NextRequest) {
  const config = readConfig(process.env);
  if ('missing' in config) {
    console.error('token endpoint not configured; missing:', config.missing.join(', '));
    return reply({ error: 'unavailable' }, 503);
  }
  const body = (await req.json().catch(() => ({}))) as { turnstile_token?: unknown };
  const ip = clientIp(req);
  const now = new Date();

  try {
    const admission = await admit(limitsFromEnv(process.env), {
      isHuman: () => verifyTurnstile(body.turnstile_token, ip, config.turnstileSecret),
      liveCalls: () => liveCalls(config.livekit),
      countVisitorCall: () =>
        config.counter.increment(visitorKey(ip, config.livekit.apiSecret, now), HOUR),
      // Two days, so the key outlives its UTC day wherever the request lands.
      countDailyCall: () => config.counter.increment(dayKey(now), 2 * DAY),
    });
    if (!admission.ok) {
      console.info('call refused:', admission.reason);
      return reply({ error: admission.reason }, statusFor(admission.reason));
    }
    const participantToken = await callToken(config.livekit);
    console.info('call admitted');
    return reply({ server_url: config.livekit.url, participant_token: participantToken }, 201);
  } catch (error) {
    // Redis or LiveKit unreachable: refuse rather than hand out calls nobody counted.
    console.error('token endpoint failed:', error);
    return reply({ error: 'unavailable' }, 503);
  }
}
