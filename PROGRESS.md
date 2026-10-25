# PROGRESS.md

Session log for voice-agent-reference. Newest entry at the top. Update at the end of every session.

## Current state

- **Milestone:** M4 Web call page deployed (2026-10-25): https://riley-kestrel-comfort.vercel.app.
  Closes after Dev's browser calls (desktop and phone).
- **Location:** `C:\Users\Devendra\Projects\Riley - HVAC`. Repo: https://github.com/waghdev/voice-agent-reference
  (private until M7). LiveKit project: `riley-kestrel-comfort-heating-a` (Build).
- **Stack as built:** Deepgram `nova-3` STT + Aura-2 TTS (Dev's key), LLM
  `google/gemini-3.1-flash-lite` on LiveKit Inference (free Build credit), `inference.TurnDetector()`,
  bundled Silero VAD, ai-coustics `QUAIL_L`.
- **Deployed:** `riley` runs on LiveKit Cloud in `us-east` (Build plan), so latency can be measured
  the way visitors will get it. Office ambience and keyboard typing are on.
- **Next step:** Dev calls Riley from https://riley-kestrel-comfort.vercel.app on a laptop and a
  phone (book an appointment once). Then Claude reads the Vercel and agent logs (call admitted,
  counters, greeting timing) and closes M4.
- **Web page:** `web/` (Next.js), Vercel project `riley-kestrel-comfort` (scope
  `devs-projects-1e3f5727`), deploys on push when `web/` changes. The Vercel plugin can't see this
  project (404), so use the CLI (`npx vercel ... --scope devs-projects-1e3f5727`). Local: `cd web && pnpm dev` with `web/.env.local` (LiveKit values only; Turnstile and
  the counters use test/in-memory stand-ins locally).
- **Calendar and leads in the cloud:** SQLite files inside the container, reset on each deploy.
  No CRM is reachable from the cloud, so leads wait in the container's outbox (by design; see
  decisions.md). Locally: `uv run uvicorn mock_crm.app:from_env --factory --port 8080`.
- **Blockers:** none.
- **Cloud logging:** back to INFO since 2026-10-22 (it was DEBUG briefly to diagnose the first-turn
  wait; DEBUG logs include transcripts, so keep it off once visitors can call).

## M1 quality-bar gaps carried into M2 and later (Dev decided, 2026-10-21)

- **Short answers wait 2.5 s** (5 of 14 cloud turns): the turn detector isn't confident after a
  name or digits, so it waits its full `max_delay`. Fix in M2: while Riley is collecting a name,
  number or ZIP (known from `CallState`), lower `max_delay` to about 1 s; keep 2.5 s for open
  answers so mid-sentence pauses aren't cut off. Normal turns are already at target.
- **Greeting start 1.4–1.9 s** (target 1 s): mostly the agent joining the room. Measure "caller
  connects → first audio" from the web page in M4, then decide.
- **Name repetition** ("Thanks, Jordan" every turn): code fix in M2 once the name is in `CallState`.

## How to call Riley

- Deployed agent: Agent Console, `riley` in us-east (link from `lk agent deploy`, or cloud.livekit.io
  → Agents). Stop any local `dev` worker first, or calls may go to it.
- Local: `uv run python -m agent.main dev`, then the Agent Console; or `... console` for mic and
  speakers in the terminal.
- After calls: `lk agent logs > agent.log` during the call, then `scripts/metrics_from_logs.py` and
  `scripts/latency_report.py`.

## Account checklist

- [x] LiveKit Cloud sign-in (`lk cloud auth`, done by Dev); `.env` LiveKit values written with
      `lk app env -w -d .env`
- [x] Deepgram and Google keys in `.env` (Dev); both checked with free calls
- [x] Gemini key's project is on the Free plan (Dev checked in AI Studio)
- [x] LiveKit CLI 2.19.0 installed (winget)
- [x] LiveKit Agent Skills installed in `.claude/skills/` (see decisions.md for the caveats)
- [x] `livekit-docs` MCP server in `.mcp.json` (Claude Code asks once to approve it)
- [x] `.env` created from `.env.example` (gitignored, `GEMINI_MODEL=gemini-3.5-flash-lite`)
- [x] GitHub repo created, private, pushed; CI green
- [x] (M4) Vercel account (Hobby, free): exists, connected to Claude Code's Vercel plugin
- [x] (M4) `npx vercel login` (Dev); secrets set from `.env` by the CLI, never through chat
- [x] (M4) Upstash Redis, free plan, connected to the Vercel project (Dev)
- [x] (M4) Cloudflare Turnstile widget; keys in `.env` and Vercel (Dev)
- [x] (M4) Vercel's GitHub app can see `voice-agent-reference`: deploy on push (Dev)
- [ ] (M6) Claim the 1 free US local number in LiveKit Cloud

## Milestones

- [x] M0 Setup (2026-10-20)
- [x] M1 Talking agent (2026-10-21; latency gaps above carried into M2/M4)
- [x] M2 Decision layer (2026-10-22; 244 unit + 11 behavior tests; latency gap accepted by Dev)
- [x] M3 Booking and CRM (2026-10-25; 353 unit + 20 behavior tests; Dev's booking call "sounds
      right")
- [ ] M4 Web call page (in progress)
- [ ] M5 Evals and quality
- [ ] M6 Phone
- [ ] M7 Ship

## Quality bar scorecard (fill from M1 on; targets in CLAUDE.md section 4)

| Check | Target | Latest result | Date |
| --- | --- | --- | --- |
| Web response latency p50 / p90 | ≤ 900 / 1,400 ms | **1,231 / 2,635 ms** with the M2 decision layer (6 calls, 17 turns). Later turns p50 1,119 ms (the spoken "Got it." keeps tool turns at 0.8–1.2 s); first turns p50 2,572 ms (4 of 6 hit the 2.5 s `max_delay`; being diagnosed). M1: 1,260 / 2,564. Not met yet | 2026-10-22 |
| Phone response latency p50 / p90 | ≤ 1,200 / 1,800 ms | | |
| Greeting start after connect | ≤ 1,000 ms web | 1,361 ms (live TTS) and 1,920 ms (pre-rendered clip), from session start. Joining the room and linking the caller took 1.3 s of the second; TTS was never the bottleneck. Measure "caller connects → first audio" from the web page in M4. Not met | 2026-10-21 |
| Barge-in stop time | ≤ 300 ms | | |
| Backchannels ignored | yes | | |
| Numbers, ZIPs, times spoken correctly | yes | Code step before TTS (`spoken.py`, 35 unit tests); Dev's cloud calls didn't flag any | 2026-10-22 |
| Silence handling and clean end-call | yes | Gate-ended calls hang up in code; no second goodbye; clean process exit in cloud; behavior tests green | 2026-10-22 |
| Scenario suite pass rate | 100% | | |
| QA grader: critical findings | 0 | | |
| Dev's listening check vs Retell standard | pass | Dev, after 7 M2 cloud calls: "I don't feel any latency... the agent responds quickly" (on headphones). Accepted the measured gap (1,231 / 2,635 ms p50/p90) | 2026-10-22 |

## Quota and cost log

Record free-tier usage observations here (agent minutes, inboun d minutes, Deepgram credit left,
Gemini rate-limit hits). Target: $0.

| Date | Observation |
| --- | --- |
| 2026-10-22 | **M3 testing on LiveKit Inference:** about 12 behavior-suite runs (full or partial) and ~40 text-mode debugger turns. Estimate ~$0.20 of the $2.50 monthly credit (one full suite run is ~$0.01–0.02 with the judge). No audio-mode turns. |
| 2026-10-20 | LiveKit Build allowances are hard caps: requests fail at the limit, with no overage billing ([quotas page](https://docs.livekit.io/deploy/admin/quotas-and-limits.md)). |
| 2026-10-20 | Build: 1,000 agent session min/month, 5 concurrent sessions, $2.50/month Inference credit, 1 US local number + 50 inbound min, 350 text / 60 audio simulation turns. Shared across all of Dev's free projects. |
| 2026-10-20 | Turn detector (`inference.TurnDetector`): 7,500 requests/month when self-hosted; requests from agents deployed to LiveKit Cloud don't count. At the cap it falls back to the local `v1-mini` model. Adaptive interruptions: 40,000 requests/month self-hosted, then falls back to VAD-based detection. |
| 2026-10-20 | **Gemini free tier is too slow for voice.** Dev's key (project on Free), from Dev's machine (plain round trip to Google 0.2–0.5 s), ~16:30–17:00 UTC, 4 runs each: `gemini-3.5-flash-lite` streaming time to first token median **16.3 s** (11–28 s); Priority via the Interactions API median 17.7 s; `serviceTier: priority` on generateContent median 13.7 s, but the response header said `standard` (silently downgraded). `gemini-3.8-flash`: three of four 503 "high demand" or timeout, one success at 60 s. Target total response is ≤ 0.9 s p50. Rule 8: Dev decides the LLM. |
| 2026-10-20 | LiveKit Inference LLM benchmark (6 models × 8 calls, then 4 × 24): about 300 tiny requests, well under $0.05 of the $2.50 credit. Time to first token is ~1 s from India (gateway round trip 0.2–0.3 s); gpt-4.1-nano was best (0.76 s reply p50). Table in docs/decisions.md. |
| 2026-10-22 | **M2 cloud test calls (6)** after a cold start: outcomes incomplete (twice), out_of_area, not_offered, callback_requested, safety_redirect, each as Dev intended except call 1. Call 1 closed as `user_initiated` (our code or `end_call`, not a hang-up) while Dev was still talking; a tool's spoken "Got it." then raised "AgentSession is closing" (fixed; who-ended-the-call logging added). First turns: 4 of 6 waited exactly ~2.5 s, not reproducible with synthesized speech locally (probability 0.46–0.48, 0.3 s). Hypothesis: louder office-chatter ambience reaching Dev's mic. Cloud debug logging on to read the detector's probabilities. One hosted turn-detector timeout (fell back to the local model). Greeting start 1.5–2.3 s. |
| 2026-10-21 | **Second cloud call** (new version): 9 turns. Normal turns 757–1,260 ms total; three turns sat at exactly 2,501–2,507 ms end-of-utterance (the `max_delay` cap). TTS first audio down to ~50 ms on a warm connection; LLM 402–665 ms. Clean exit: no "did not exit in time", no warnings. Greeting start 1,920 ms, 1.3 s of it joining the room. |
| 2026-10-21 | **First cloud call** (us-east): total p50 1,308 ms, p90 2,652; end of utterance 387 ms; STT 234 ms; LLM 735 ms; TTS 136 ms; greeting start 1,361 ms. Logs: one hosted turn-detector timeout (fell back to the local mini model); the job hung 10 s at exit and was killed (fixed: background audio now closes before the room is deleted; verify on the next call). |
| 2026-10-21 | **Latency diagnosis.** Dev's Agent Console calls (web, agent local in India): total p50 2.8 s, p90 5.1 s; end of utterance p50 2.5 s; STT final 1.3–3.8 s; LLM 0.84 s; TTS 0.38 s. Clean speech through the local audio pipeline (debugger `--audio`): end of turn ~0.5 s, LLM 0.8–1.2 s, TTS 0.36–0.56 s, total ~1.9–2.1 s. After a spoken ZIP the turn detector's end-of-turn probability was 0.28 (threshold 0.36), so it waited the full 2.5 s `max_delay` (total 3.2 s); Dev's 2,505 ms turn matches. Dev's 3.8 s turns waited on Deepgram's final transcript, which clean audio doesn't reproduce. Each stage includes India↔US round trips, so the web number has to come from the deployed agent. |
| 2026-10-21 | Debugger audio mode: 5 spoken lines through LiveKit Inference TTS (a few hundred characters of the credit). |
| 2026-10-20 | M1 work on LiveKit Inference: ~25 behavior-suite runs plus debugger calls, roughly $0.20–0.30 of the $2.50 credit (estimate from token counts; check the Usage page in LiveKit Cloud). One suite run is about $0.01. |
| 2026-10-20 | Deepgram: 7 voice samples, ~3,700 characters of Aura-2 (about $0.11 of the $200 credit). First byte for a 534-character request was 0.8–1.1 s from India. |
| 2026-10-20 | Text-mode debugger (no audio), from India: LLM first token p50 815 ms, p90 1,046 ms (11 turns); greeting start 1.5 s, and 4.0 s on a cold start, already over the 1 s target before TTS. If the live session confirms it, pre-synthesize the fixed greeting at startup (`say()` accepts audio). |
| 2026-10-20 | Deepgram key works (projects endpoint 200). The key has no `billing:read` scope, so check the credit balance in the Deepgram console. |
| 2026-10-20 | Noise cancellation: ai-coustics `QUAIL_VF_S`/`QUAIL_VF_L` and Krisp VIVA cost extra. Krisp NC and ai-coustics `QUAIL_L` have no extra charge. LiveKit's own starter uses `QUAIL_VF_S`, so copying it would break rule 2. Build availability is not stated on the docs page; check the pricing page at M1. |

## Open questions

- **M1 choices approved by Dev (2026-10-20):** `inference.TurnDetector()`, a no-extra-charge noise
  cancellation model (`QUAIL_L` or Krisp NC), Gemini's default temperature of 1, fastest free Flash
  model by measurement. Details and reasons in docs/decisions.md.
- **LLM route changed (Dev approved):** the Gemini free tier measured 11–28 s to first token, so the
  LLM is on LiveKit Inference within the free credit. After the behavior suite it's
  `google/gemini-3.1-flash-lite` (nano failed it), which the credit covers for ~220 calls/month,
  shared with dev testing and any debugger audio-mode TTS. At M4 the public page's
  `MAX_SESSIONS_PER_DAY` (40 in `.env.example`) must drop to about 5, and Riley must close politely
  when the credit is exhausted.
- **Latency budget is tight:** LLM time to first token alone is ~0.8–1.0 s from India, against a
  0.9 s total target (end of turn + LLM + TTS). Local M1 numbers will include India↔US network
  hops for STT, LLM and TTS; the headline numbers come from the deployed agent (M4). If they still
  miss, levers are preemptive generation, prompt size, and inference priority (cost not documented;
  check before using).
- **Cold starts on Build:** the quotas page says agents may shut down after all sessions end, adding
  "up to 10 to 20 seconds of delay" before the agent joins. That conflicts with the ≤ 1,000 ms
  greeting target for a visitor's first call. Measure at M4; the page needs a "connecting" state
  either way. Possible rule 8 conversation.
- Web starter: agent-starter-react vs the web embed starter. Decide at M4 (embed could later sit on
  scaileai.com; check Vercel Hobby terms first).

## Session log

### 2026-10-25: M4 web call page deployed

- Dev did the account steps (Vercel CLI login, Turnstile keys, Upstash, GitHub app access).
- Secrets copied from `.env` to Vercel by the CLI (sensitive, production); first production
  deploy from a push, functions in iad1.
- Live checks: page public and branded; `/api/token` refuses a missing or fake Turnstile token
  (403), so the real secret and full config are in place; GET is 405. Firewall rule created
  through the API (it reports "not found" until the first deploy) and confirmed: 10 requests a
  minute pass, the 11th gets 429.
- Not yet proven: the Upstash counters (they need a real Turnstile pass, so Dev's first browser
  call is the test).

### 2026-10-25: M4 web call page built

- Dev approved the design: React starter, `/api/token` behind Turnstile, 3 calls per visitor per
  hour, 5 a day, under 4 live calls, Upstash counters, Vercel Hobby.
- Built: `web/` from LiveKit's starter (imported unchanged, then changed in reviewable commits),
  `lib/gatekeeper.ts` (pure, 14 vitest tests with counters and Turnstile), Kestrel branding,
  voice-only call view, friendly refusal messages, browser greeting timing sent to the agent.
- Agent: a pre-rendered "trouble on my end" line and a hang-up when a model fails for good
  (found in the debugger: 1.8.8 only closes after 3 unrecoverable errors, so the documented
  pattern left dead air); logs the page's greeting timing as `client_greeting` metrics.
  Deployed.
- Checked: the local token endpoint against the real LiveKit project (403 without Turnstile,
  three admitted, 429 on the fourth); an endpoint token brought the deployed Riley into a
  fresh room as soon as the connection finished.
- CI: new `web` job (lint, format, tests, build), green. 367 Python unit tests.

### 2026-10-25: M3 closed

- Dev booked an appointment on the deployed agent in Agent Console: "sounds right".

### 2026-10-22: M3 booking and CRM built and deployed

- Dev approved the design: one agent, leads wait in the outbox when no CRM is reachable (the
  cloud), bookings in SQLite, read-back enforced in code, CRM delivery off the caller's path, a
  filler line for slow calendar calls, httpx + FastAPI.
- Built: `calendar.py` (windows, priority same-day rule, capacity, idempotent booking),
  `crm_client.py` (outbox, retries with backoff and jitter, idempotency keys, background sender),
  `mock_crm/` (FastAPI, one lead per key, failure switch), booking gates and steps, three tools
  (`find_windows`, `choose_window`, `book_appointment`), `scripts/redeliver_outbox.py`.
- Debugger, end to end against the local mock CRM set to fail twice: intake, filler line, two
  windows, read-back, booked, lead delivered on the third attempt (one copy), one goodbye.
- Bugs found, each with a test before the fix: the model invented `vulnerable_occupant="infant"`
  (1 in 5; now needs the caller's own words, checked against the transcript); "stopped cooling"
  read as working, losing the priority (3 of 3; parameter renamed for the model); TTS said
  "between noon to two" (now "and"). Tests that rejected correct replies: "Thanks for calling."
  and "Thanks for checking with us." are goodbyes; "I'll book you for..." in a read-back is fine.
- Tests: 353 unit (CI), 20 behavior. Final full behavior run: 20 of 20 (earlier runs during
  Dev's connection drop failed on network errors, not on the code).
- Deployed to LiveKit Cloud (us-east); the worker registered cleanly.

### 2026-10-22: M2 closed

- Dev's 6 test calls: all outcomes right; one call closed early by our code (`user_initiated`) and a
  tool crashed on a closing session (fixed: best-effort acknowledgement; every tool decision and
  who ended the call is now logged).
- Seventh call with debug logs: first turn fine (444 ms), so the earlier 2.5 s first turns stay
  unexplained (Dev uses headphones, so not ambience). Short-answer endpointing confirmed (1.0 s
  cap used on the name). A ZIP split across two turns, and a stray late turn was recorded after
  the call was decided: fixed (digits wait at least 0.6 s; tools are no-ops once decided).
- Dev: responses feel quick; measured gap accepted. Debug logging off again.
- Behavior tests fixed where they rejected correct replies ("take care" is a goodbye; offering
  normal service to a prompt injection is right). 3 clean runs.

### 2026-10-21: M2 decision layer built and deployed

- Structure (Dev approved): one agent with tools. `config.py` (typed `BusinessConfig`),
  `parsing.py` (spoken digits, ZIP+4, phone formats), `state.py`, `gates.py` (safety, area,
  offered, urgency, readiness with NOT_BOOKABLE, two-strikes retry, callback), `intake.py` (tool
  logic), `tools.py` (LiveKit wrappers), `spoken.py` (numbers, NameGuard, LeadingAckGuard).
- Code now enforces what the prompt couldn't: exact safety script and hang-up; hang-up after a
  gate ends the call; no second goodbye; 1 s `max_delay` for short answers; a spoken "Got it."
  during tool turns; name at most once; numbers spoken naturally. Details and measurements in
  decisions.md.
- Bugs found in debugger and behavior runs, each with a test first: placeholder arguments
  ("unknown"); indoor temperature 0; two goodbyes or none on gate-ended calls; double
  acknowledgement; behavior tests that punished correct behavior (fixed in the tests).
- Tests: 239 unit (CI), 11 behavior (`-m llm`, 4 clean runs at the end).
- README: "The decision layer" section written.
- Deployed to LiveKit Cloud (us-east).

### 2026-10-21: M1 closed

- Voice: Aura-2 Andromeda (Dev, by listening; American English, `en-US`).
- Background audio: office ambience and keyboard typing while Riley thinks, levels picked by Dev
  from measured previews, then +3 dB after a live call.
- Deployed to LiveKit Cloud us-east (Dockerfile, minimal secrets, `metrics_from_logs.py`).
- Bugs from cloud calls, each with a test before the fix: the greeting's disclosure sentence in a
  different-sounding voice (now one pre-rendered clip); the job hanging 10 s at exit (background
  audio now closes before the room is deleted); replayed log lines double-counting turns.
- Latency: agent on Dev's PC 2.8 s p50; deployed 1.26 s p50 / 2.56 s p90 (14 turns). Normal
  turns are at target; short answers wait the 2.5 s `max_delay`. Dev chose to fix that in M2 with
  context-aware endpointing and close M1 with the gap recorded.

### 2026-10-20: M1 agent built and text-tested

- `src/agent/main.py`: Riley session with Deepgram nova-3 + Aura-2, LiveKit Inference LLM, audio
  turn detector, bundled Silero VAD, ai-coustics `QUAIL_L`, non-interruptible greeting,
  `EndCallTool`, 7 s silence check-ins, 5-minute limit, room deleted on every close. Every API
  checked with `lk docs` and the installed 1.8.8 source (the MCP server wasn't live this session).
- `prompts.py`, `config.py`, `metrics.py` (per-turn JSONL from `ChatMessage.metrics`),
  `silence.py`, `scripts/latency_report.py`; 46 unit tests (CI green).
- Driving Riley in `lk agent debugger` found six bugs. Each became a test before its fix (rule 7):
  hung up mid-call when input was typed (unit test); re-asked for the problem; name on consecutive
  turns; invented "yes, we do duct cleaning"; `end_call` fired four times with two goodbyes; then
  `end_call` looped (behavior tests, `tests/behavior/`, marked `llm`).
- Switched the LLM from gpt-4.1-nano to gemini-3.1-flash-lite: the behavior suite measures
  instruction following, which the speed benchmark didn't (decisions.md).
- Seven Aura-2 voice samples generated in `voice-samples/` (gitignored) for Dev to choose from.

### 2026-10-20: M0 done: keys, LLM route and model

- Dev signed in to LiveKit Cloud; `lk app env` wrote the LiveKit values into `.env`. A
  length-and-equality check (no values printed) confirmed Dev's other keys were untouched.
- Deepgram and Gemini keys verified with free calls. The Gemini free tier was far too slow
  (median 16 s to first token), so with Dev's approval the LLM moved to LiveKit Inference.
- Benchmarked LiveKit Inference models; picked `openai/gpt-4.1-nano` (fastest p50 and p90, 12/12
  tool calls, cheapest). Added `LLM_MODEL` to `.env` and `.env.example`.
- Temperature: back to low (CLAUDE.md section 4), since the "default 1" exception was for Gemini 3.

### 2026-10-20: M0 tooling, repo and CI

- Dev approved the four M1 choices; logged in docs/decisions.md.
- Checked Gemini pricing: Flash models have a free tier; "paid" comes from a billing-linked project.
- CLAUDE.md now points at `C:\Users\Devendra\Projects\Riley - HVAC`.
- Installed LiveKit CLI 2.19.0 and LiveKit's seven Agent Skills (`.claude/skills/`, `skills-lock.json`).
  Read them: where they assume LiveKit Inference, CLAUDE.md section 10 wins (caveats in decisions.md).
- `lk cloud auth` refuses to run without an interactive terminal, so it's on Dev's list.
- Created `.env` from `.env.example` (gitignored, keys empty).
- Created https://github.com/waghdev/voice-agent-reference (private) and pushed, after a secret scan
  of the full history. The first CI run failed: `astral-sh/setup-uv` has no floating `v10` tag. Pinned
  `setup-uv@v10.3.0`, `checkout@v7.0.1` and `ubuntu-24.04`; CI green in 16 s.
- Dev's standing preference: Claude does everything it can and only escalates what needs Dev
  (saved to Claude Code memory).

### 2026-10-20: M0 scaffold

- Added the LiveKit docs MCP server (`livekit-docs`, project scope, `.mcp.json`). It's pending Dev's
  approval and wasn't live in this session, so APIs were checked over HTTP (`llms.txt` and `.md` pages).
- Installed uv 0.13.2 (winget). Created the uv project: Python 3.13, `uv_build`, import name `agent`.
- Pinned `livekit-agents[deepgram,google,silero]==1.8.8`, `python-dotenv==1.2.4`, `pyyaml==6.0.3`;
  dev: pytest, pytest-asyncio, ruff (exact pins in `pyproject.toml`, full tree in `uv.lock`).
  `yarl` resolved to 1.25.1, which has cp313 wheels, so the starter's `yarl<1.24` constraint isn't needed.
  No turn detector or noise cancellation package yet; those wait for the M1 proposals.
- `livekit-agents` is on 1.8.8, not the 1.5 line CLAUDE.md mentions (rule 6: docs win).
- `config/business.yaml` transcribed from `docs/business.md` (facts and thresholds; rules go in gates).
- `tests/unit/test_business_config.py`: drift checks between the YAML and the spec.
- CI (`.github/workflows/ci.yml`): `uv sync --locked`, `ruff check`, `pytest -m "not llm"`. It runs
  once the repo is on GitHub.
- `git init` on `main`; first commit.

### 2026-10-20: Project created

- CLAUDE.md, PROGRESS.md, README skeleton, docs/business.md, docs/decisions.md, .env.example, .gitignore.
- Updated same day: web calls are the primary channel (public page for visitors), phone is secondary;
  Retell-grade quality bar added to CLAUDE.md section 4.
- Stack confirmed against current free tiers: LiveKit Cloud Build, LiveKit free US number,
  Deepgram STT + TTS, Gemini Flash free tier, Silero + LiveKit turn detector.
