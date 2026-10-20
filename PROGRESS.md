# PROGRESS.md

Session log for voice-agent-reference. Newest entry at the top. Update at the end of every session.

## Current state

- **Milestone:** M0 Setup. Scaffold done and committed; M0 closes when Dev's account checklist is done.
- **Location:** `C:\Users\Devendra\Projects\Riley - HVAC` (CLAUDE.md says `...\voice-agent-reference`;
  see open questions). The Python project and the GitHub repo are named `voice-agent-reference`.
- **Next step:** Dev finishes the account checklist and fills `.env`. Then Dev answers the four M1
  proposals below, and M1 starts.
- **Blockers:** M1 needs the LiveKit, Deepgram and Google AI Studio keys.

## Account checklist (Dev)

- [ ] LiveKit Cloud account, Build (free) plan, new project; note URL, API key, API secret
- [ ] LiveKit CLI installed (`winget install LiveKit.LiveKitCLI`) and authenticated (`lk cloud auth`)
- [ ] Optional: `lk skills install` in the repo (LiveKit's Agent Skills for Claude Code, including
      `debugging-livekit-agents`)
- [ ] Approve the `livekit-docs` MCP server when Claude Code asks (it's in `.mcp.json`)
- [ ] Deepgram account; API key ($200 signup credit)
- [ ] Google AI Studio API key (Gemini free tier); note which Flash model ids are on the free tier and
      their rate limits (see M1 proposal 4)
- [ ] (M4) Vercel account (Hobby, free) for the public web-call page
- [ ] (M4) Cloudflare account; Turnstile site key and secret (free)
- [ ] (M6) Claim the 1 free US local number in LiveKit Cloud
- [ ] GitHub repo `voice-agent-reference`, private until M7; add it as `origin` and push so CI runs

## Milestones

- [ ] M0 Setup (scaffold done 2026-10-20; waiting on accounts and keys)
- [ ] M1 Talking agent
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
| Silence handling and clean end-call | yes | | |
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
| 2026-10-20 | Noise cancellation: ai-coustics `QUAIL_VF_S`/`QUAIL_VF_L` and Krisp VIVA cost extra. Krisp NC and ai-coustics `QUAIL_L` have no extra charge. LiveKit's own starter uses `QUAIL_VF_S`, so copying it would break rule 2. Build availability is not stated on the docs page; check the pricing page at M1. |

## Open questions

### M1 proposals (need Dev's yes before M1 code)

The docs have moved on since CLAUDE.md was written (rule 6: the docs win, so these are flagged here).

1. **Turn detector:** use `inference.TurnDetector()`, the audio-based model LiveKit now recommends.
   The text-based `MultilingualModel` (`livekit-plugins-turn-detector`) is deprecated and will be
   removed in 2.0. It runs on LiveKit Inference but uses its own free allowance (above), not the
   $2.50 credit that CLAUDE.md section 10 says to avoid. Recommendation: yes.
2. **Noise cancellation:** ai-coustics `QUAIL_L` or Krisp NC (both no extra charge), not the
   starter's `QUAIL_VF_S`. Compare by listening at M1 once Build availability is confirmed.
3. **LLM temperature:** LiveKit's Gemini docs say to leave `temperature` at its default of 1 for
   Gemini 3 models, because other values can cause looping or odd reasoning. CLAUDE.md section 4
   asks for a low temperature. Recommendation: follow the docs, keep consistency through the short
   prompt, exact scripts and gates, and measure it in M5. If tone drifts, revisit.
4. **Gemini model id:** the plugin docs list `gemini-3.8-flash`, `gemini-3.5-flash`,
   `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite` as current. Dev checks which are on the AI
   Studio free tier and their rate limits; we pick the fastest one that handles tool calls well.

### Other

- **Cold starts on Build:** the quotas page says agents may shut down after all sessions end, adding
  "up to 10 to 20 seconds of delay" before the agent joins. That conflicts with the ≤ 1,000 ms
  greeting target for a visitor's first call. Measure at M4; the page needs a "connecting" state
  either way. Possible rule 8 conversation.
- **Project folder:** the repo lives in `Riley - HVAC`, not `voice-agent-reference` as CLAUDE.md
  says. Everything works with the space in the path. Either rename the folder (Claude Code's memory
  for this project is keyed to the path, so it would start fresh) or update CLAUDE.md. Dev's call.
- Agent structure: single Agent with tools vs handoffs/tasks. Decide at M2 after checking current docs.
- Deepgram Aura voice vs Cartesia: compare at M1 by listening; Deepgram is the default.
- Web starter: agent-starter-react vs the web embed starter. Decide at M4 (embed could later sit on
  scaileai.com; check Vercel Hobby terms first).

## Session log

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
