/** What a visitor sees when the token endpoint says no (see lib/gatekeeper.ts). */

export type RefusalCode = 'bot_check' | 'busy' | 'rate_limited' | 'daily_cap' | 'unavailable';

export const REFUSAL_MESSAGES: Record<RefusalCode, string> = {
  bot_check: "We couldn't confirm you're human. Please complete the check and try again.",
  busy: 'Riley is on other calls right now. Please try again in a few minutes.',
  rate_limited: "You've reached the demo's call limit for now. Please try again in an hour.",
  daily_cap: "Riley has taken all of today's demo calls. Please come back tomorrow.",
  unavailable: 'The demo is busy, try again later.',
};

export function refusalMessage(code: unknown): string {
  return typeof code === 'string' && code in REFUSAL_MESSAGES
    ? REFUSAL_MESSAGES[code as RefusalCode]
    : REFUSAL_MESSAGES.unavailable;
}
