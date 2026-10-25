# web: the "Talk to Riley" page

A browser page where anyone can call Riley, the voice agent in `src/agent`, without a phone.
Next.js on Vercel's free Hobby plan.

- `app/api/token/route.ts`: issues a LiveKit token for one call, server-side only. Before it
  does, `lib/gatekeeper.ts` checks, in order: a Cloudflare Turnstile bot check, how many calls are
  live (LiveKit's free plan allows 5 at once), the visitor's calls this hour, and today's total.
  The room name and agent dispatch are set on the server, never taken from the browser.
- `components/app/`: the page (welcome view, Turnstile widget, call view). Voice only.
- `hooks/useGreetingTiming.ts`: measures "call connected → Riley's first words" in the browser
  and sends it to the agent, which logs it with its other latency metrics.

## Run locally

```shell
cp .env.example .env.local   # fill in the three LiveKit values; leave the rest blank
pnpm install
pnpm dev                     # http://localhost:3000
pnpm test                    # unit tests (no network)
```

Locally, Turnstile uses Cloudflare's always-pass test keys and the counters stay in memory. In
production, missing Turnstile or Upstash settings make the token endpoint refuse every call
(fail closed), since each call spends free quota.

## Credits

Built on LiveKit's [agent-starter-react](https://github.com/livekit-examples/agent-starter-react),
MIT licensed (see `LICENSE`, copyright LiveKit, Inc.).
