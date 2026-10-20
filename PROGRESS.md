# PROGRESS.md

Session log for voice-agent-reference. Newest entry at the top. Update at the end of every session.

## Current state

- **Milestone:** M1 Talking agent, in progress. The agent is built and checked in text mode; it
  needs Dev's voice session (below) for the voice choice, live latency and barge-in checks.
- **Location:** `C:\Users\Devendra\Projects\Riley - HVAC`. Repo: https://github.com/waghdev/voice-agent-reference
  (private until M7). LiveKit project: `riley-kestrel-comfort-heating-a` (Build).
- **Stack as built:** Deepgram `nova-3` STT + Aura-2 TTS (Dev's key), LLM
  `google/gemini-3.1-flash-lite` on LiveKit Inference (free Build credit), `inference.TurnDetector()`,
  bundled Silero VAD, ai-coustics `QUAIL_L`.
- **Next step:** Dev's M1 voice session: pick a voice from `voice-samples/`, then talk to Riley in
  the Agent Console (steps in "M1 voice session" below). Claude then runs the latency report,
  tunes, and closes M1.
- **Blockers:** M1 can't close without that session (listening and live audio).

## M1 voice session (Dev, about 10 minutes)

1. Restart VS Code (so its terminals see `uv` and `lk`, which were installed during the session).
2. Listen to the seven samples in `voice-samples\` (same script, read by each voice; the script
   is in `voice-samples\script.txt`). Pick one or two.
3. In a VS Code terminal: `uv run python -m agent.main dev` (leave it running).
4. Open https://cloud.livekit.io, pick the project, go to Agents, and use **Launch Console** for
   `riley`. Allow the microphone.
5. Try: a normal intake call; pause mid-sentence ("my AC is... um... making a clicking noise");
   say "mm-hmm" while Riley talks (it should keep going); cut in with "wait, actually" (it should
   stop fast); stay silent for about 20 s (two check-ins, then goodbye); and end with "that's all,
   bye".
6. Tell Claude which voice and how it felt. Claude reads `metrics/` and writes the numbers here.

Fallback if the console isn't reachable: `uv run python -m agent.main console` talks through the
PC's mic and speakers in the terminal (no WebRTC, so its latency isn't the web number).

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
- [ ] (M4) Vercel account (Hobby, free) for the public web-call page
- [ ] (M4) Cloudflare account; Turnstile site key and secret (free)
- [ ] (M6) Claim the 1 free US local number in LiveKit Cloud

## Milestones

- [x] M0 Setup (2026-10-20)
- [ ] M1 Talking agent (built and text-tested; waiting on Dev's voice session)
- [ ] M2 Decision layer
- [ ] M3 Booking and CRM
- [ ] M4 Web call page
- [ ] M5 Evals and quality
- [ ] M6 Phone
- [ ] M7 Ship

## Quality bar scorecard (fill from M1 on; targets in CLAUDE.md section 4)

| Check | Target | Latest result | Date |
| --- | --- | --- | --- |
| Web response latency p50 / p90 | ≤ 900 / 1,400 ms | | |
| Phone response latency p50 / p90 | ≤ 1,200 / 1,800 ms | | |
| Greeting start after connect | ≤ 1,000 ms web | | |
| Barge-in stop time | ≤ 300 ms | | |
| Backchannels ignored | yes | | |
| Numbers, ZIPs, times spoken correctly | yes | | |
| Silence handling and clean end-call | yes | Text mode: check-ins, close and end_call work; unit and behavior tests green. Audio not yet checked | 2026-10-20 |
| Scenario suite pass rate | 100% | | |
| QA grader: critical findings | 0 | | |
| Dev's listening check vs Retell standard | pass | | |

## Quota and cost log

Record free-tier usage observations here (agent minutes, inbound minutes, Deepgram credit left,
Gemini rate-limit hits). Target: $0.

| Date | Observation |
| --- | --- |
| 2026-10-20 | LiveKit Build allowances are hard caps: requests fail at the limit, with no overage billing ([quotas page](https://docs.livekit.io/deploy/admin/quotas-and-limits.md)). |
| 2026-10-20 | Build: 1,000 agent session min/month, 5 concurrent sessions, $2.50/month Inference credit, 1 US local number + 50 inbound min, 350 text / 60 audio simulation turns. Shared across all of Dev's free projects. |
| 2026-10-20 | Turn detector (`inference.TurnDetector`): 7,500 requests/month when self-hosted; requests from agents deployed to LiveKit Cloud don't count. At the cap it falls back to the local `v1-mini` model. Adaptive interruptions: 40,000 requests/month self-hosted, then falls back to VAD-based detection. |
| 2026-10-20 | **Gemini free tier is too slow for voice.** Dev's key (project on Free), from Dev's machine (plain round trip to Google 0.2–0.5 s), ~16:30–17:00 UTC, 4 runs each: `gemini-3.5-flash-lite` streaming time to first token median **16.3 s** (11–28 s); Priority via the Interactions API median 17.7 s; `serviceTier: priority` on generateContent median 13.7 s, but the response header said `standard` (silently downgraded). `gemini-3.8-flash`: three of four 503 "high demand" or timeout, one success at 60 s. Target total response is ≤ 0.9 s p50. Rule 8: Dev decides the LLM. |
| 2026-10-20 | LiveKit Inference LLM benchmark (6 models × 8 calls, then 4 × 24): about 300 tiny requests, well under $0.05 of the $2.50 credit. Time to first token is ~1 s from India (gateway round trip 0.2–0.3 s); gpt-4.1-nano was best (0.76 s reply p50). Table in docs/decisions.md. |
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
- **Riley doesn't say the caller's name** (M1 prompt): "at most once" still repeated it in 1 of 4
  runs. Revisit at M5 with pass rates if Dev wants a single "Thanks, Jordan".
- **Latency budget is tight:** LLM time to first token alone is ~0.8–1.0 s from India, against a
  0.9 s total target (end of turn + LLM + TTS). Local M1 numbers will include India↔US network
  hops for STT, LLM and TTS; the headline numbers come from the deployed agent (M4). If they still
  miss, levers are preemptive generation, prompt size, and inference priority (cost not documented;
  check before using).
- **Cold starts on Build:** the quotas page says agents may shut down after all sessions end, adding
  "up to 10 to 20 seconds of delay" before the agent joins. That conflicts with the ≤ 1,000 ms
  greeting target for a visitor's first call. Measure at M4; the page needs a "connecting" state
  either way. Possible rule 8 conversation.
- Agent structure: single Agent with tools vs handoffs/tasks. Decide at M2 after checking current docs.
- Deepgram Aura voice vs Cartesia: compare at M1 by listening; Deepgram is the default.
- Web starter: agent-starter-react vs the web embed starter. Decide at M4 (embed could later sit on
  scaileai.com; check Vercel Hobby terms first).

## Session log

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
