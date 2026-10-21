# Decision log

One entry per decision: date, decision, alternatives considered, reason. Newest at the top.

## 2026-10-21: Pre-rendered greeting, hang-up order, louder background audio

- **Greeting clip:** on Dev's first cloud call, "This call may be recorded for quality." sounded like
  a different voice. The Deepgram plugin streams over a WebSocket and flushes after each segment, so
  each sentence is synthesized separately, and Aura-2 can deliver a short standalone sentence quite
  differently. The voice samples Dev approved were one request each, and sounded consistent. The
  greeting is fixed text, so `scripts/make_greeting_audio.py` renders it in one request into
  `assets/greeting.wav`, with a manifest of the exact text, voice and SHA-256. Riley plays it with
  `session.say(text, audio=...)` only if text and voice still match; otherwise live TTS. A unit test
  fails if `business.yaml`'s greeting or the default voice changes without re-rendering. Side
  benefit: the greeting no longer waits on TTS. `.gitattributes` keeps the WAV binary.
  Alternative considered: sending the greeting to TTS as one segment; rejected because it still
  costs TTS time on every call and depends on plugin internals.
- **Hang-up order:** the SDK sends "exiting", disconnects the room, *then* runs shutdown callbacks.
  Closing background audio as a shutdown callback therefore unpublished a track from a disconnected
  room, and the job hung 10 s until LiveKit killed it. Now the session close handler closes
  background audio (bounded at 2 s), then deletes the room (hanging up the caller), then ends the
  job. `RoomOptions.delete_room_on_close` is off because it deleted the room at the same moment.
- **Volumes:** Dev asked for "a little louder" after the call: +3 dB on both, ambience 2.5 → 3.5
  (~17 dB under speech, peaks −27 dBFS) and typing 0.35 → 0.5 (~12 dB under, peaks −12 dBFS). No
  clipping at either level.

## 2026-10-21: Deploy to LiveKit Cloud us-east now, to measure the real web latency (Dev approved)

- **Decision:** the agent runs on LiveKit Cloud (Build plan) in `us-east`, ahead of M4, so latency
  is measured in the setup visitors will use. It's built from the repo's `Dockerfile`.
- **Why:** with the agent on Dev's PC in India, every STT, LLM and TTS request crosses India↔US,
  which put a ~2 s floor under every turn. Tuning against that would optimize the wrong thing.
- **Region:** `us-east`, close to Deepgram and the LLM gateway; it can't be changed after creation
  (a new deployment is needed). Callers in India reach it through LiveKit's media network.
- **Secrets:** only `DEEPGRAM_API_KEY`, `LLM_MODEL`, `TTS_VOICE` and `MAX_CALL_SECONDS`, uploaded from a
  temporary file that was deleted afterwards. LiveKit injects its own credentials; the Google key
  stays local because the deployed agent doesn't use it.
- **Image:** LiveKit's uv template, adapted: Python 3.13, dependencies installed before the source
  (cached), project installed editable so `config/business.yaml` resolves, no dev tools, and the
  venv's python as the entrypoint so a cold start never re-syncs dependencies.
- **Metrics:** the cloud disk isn't kept, so `scripts/metrics_from_logs.py` rebuilds metrics JSONL
  from the "turn metrics" log lines (`lk agent logs`).
- **Cost:** $0. Build includes agent hosting; sessions use the 1,000 monthly agent minutes. Idle
  agents scale to zero, so the first call after a quiet spell can wait 10–20 s.
- **`livekit.toml`** (project subdomain and agent id) is gitignored: not secret, but it ties the
  public repo to Dev's project.

## 2026-10-21: Background audio: office ambience at 2.5, keyboard typing at 0.35 (Dev's choice)

- **Decision:** `BackgroundAudioPlayer` with LiveKit's built-in office ambience at gain 2.5, and
  keyboard typing as the "thinking" sound at 0.35, chosen with probabilities 0.5 and 0.3 (so about
  1 in 5 pauses has no typing).
- **How the levels were picked:** measured loudness against Andromeda's speech, then Dev listened to
  mixed previews (`voice-samples/ambience/`). Office at 1.0 sat ~31 dB under speech, too quiet;
  2.5 puts it ~20 dB under. Typing at 1.0 sat only ~6 dB under; 0.35 puts it ~15 dB under.
- **Note:** 2.5 is above the documented 0.0–1.0 range. It works because the player multiplies
  samples and clips them to 16-bit; if a future SDK caps volume at 1.0, the ambience gets quieter,
  not broken.
- **Licensing:** the typing clips are CC BY 4.0 (credited in the README); office ambience ships with
  LiveKit Agents. Nothing is redistributed by this repo.
- **Audio path:** the ambience plays on a separate track to the caller; Riley's STT listens to the
  caller's microphone, so it never transcribes the ambience.

## 2026-10-21: Voice is Deepgram Aura-2 Andromeda (chosen by Dev, by listening)

- **Decision:** `TTS_VOICE=aura-2-andromeda-en`.
- **How:** seven Aura-2 voices tagged for customer service read the same script (greeting,
  acknowledgement, phone number read-back, two time windows, safety line): Thalia, Harmonia, Vesta,
  Andromeda, Arcas, Neptune, Orpheus. Dev picked Andromeda.
- **Riley's gender:** Riley is a unisex name, and neither `business.md` nor the prompt gives Riley
  a gender, so the voice was chosen on sound alone; nothing else depends on it.
- **Still to check live:** how it sounds through the full pipeline in the Agent Console, and
  whether "Kestrel" needs a pronunciation entry (M2 text normalization).

## 2026-10-20: LLM switched to google/gemini-3.1-flash-lite (behavior tests beat the benchmark)

- **Decision:** `LLM_MODEL=google/gemini-3.1-flash-lite` on LiveKit Inference, at the model's
  default temperature (unset `LLM_TEMPERATURE`), with `parallel_tool_calls: False`.
- **Why:** the earlier pick, gpt-4.1-nano, was fastest in the TTFT benchmark but failed Riley's
  behavior suite: 5 of 12 passes over two runs (it re-asked for the problem, hung up as soon as it
  had the ZIP, and didn't hang up when the caller said bye). Same suite, same prompt:
  gemini-3.1-flash-lite 11/12, gpt-4.1-mini 9/12. After the prompt fixes below,
  gemini-3.1-flash-lite passed 7/7 on repeated runs. It costs ~0.15 s more time to first token
  (0.90 vs 0.76 s p50) and ~2.5× the credit per call (~220 calls/month vs ~550).
- **Temperature:** Gemini 3 again, so LiveKit's Gemini guidance applies: keep the default.
  `LLM_TEMPERATURE` exists for models where lowering it is safe.
- **Lesson:** a speed benchmark with one tool call doesn't measure instruction following; pick by
  the behavior suite, then check latency.

## 2026-10-20: M1 talking agent: how each quality-bar item is met

All APIs checked against livekit-agents 1.8.8 docs (`lk docs`) and the installed source.

- **Structure for M1:** one `Riley` agent with `EndCallTool`. Whether M2 uses one agent with tools,
  handoffs or tasks is still open (it's decided with the gates).
- **STT:** Deepgram `nova-3`, `en-US`, keyterm `Kestrel` (static, so no extra LLM calls from
  automatic keyterm detection). Deepgram Flux (`STTv2`, its own end-of-turn model) is a tuning
  option if endpointing numbers need it.
- **Turn detection:** `inference.TurnDetector()` (approved earlier). Endpointing, adaptive
  interruptions, false-interruption resume and preemptive LLM generation use the defaults, which
  already match section 4; tune from measurements.
- **VAD:** the session's bundled Silero (`inference.VAD(model="silero")`, local). The separate
  `livekit-plugins-silero` (and onnxruntime) was dropped from dependencies.
- **Noise cancellation:** ai-coustics `QUAIL_L` on the agent side. LiveKit's pricing data lists
  background noise suppression (Krisp NC, `QUAIL_L`) as included on Build; voice isolation models
  get only 100 minutes, so they're avoided.
- **Greeting:** `session.say(greeting, allow_interruptions=False)` in `on_enter`, so the recording
  disclosure can't be talked over; `EndCallTool(ignore_on_enter=True)` so it can't end the call.
- **Ending:** every way a call ends closes the session, and `RoomOptions.delete_room_on_close`
  deletes the room, which disconnects the caller (phone included) and ends the job. The tool's
  result is a custom line; the default made the model loop on `end_call`.
- **Silence:** `user_away_timeout=7` plus `SilenceMonitor` (two "Are you still there?" check-ins,
  then a fixed goodbye). Fixed lines are `say()`, not generated: identical every call, no tokens.
  Caller messages call `session.reset_away_timer()`, because typed input doesn't go through VAD.
- **Time limit:** no built-in option exists, so a task closes the call after `MAX_CALL_SECONDS`.
- **Latency metrics:** `ChatMessage.metrics` from `conversation_item_added`. The session-level
  `metrics_collected` event is deprecated. One JSON line per turn in `metrics/`; greeting start is
  measured from just before `session.start()`. On LiveKit Cloud the filesystem isn't kept, so M4
  needs another sink (logs).
- **Prompt rules that came from bugs:** each has a behavior test in `tests/behavior/`. Riley doesn't
  say the caller's name at all, because "at most once" still produced "Nice to meet you, Jordan" then
  "Thanks, Jordan" in 1 of 4 runs.

## 2026-10-20: LLM model is openai/gpt-4.1-nano on LiveKit Inference

- **Decision:** `LLM_MODEL=openai/gpt-4.1-nano`. Runner-up and first fallback:
  `google/gemini-3.1-flash-lite` on LiveKit Inference. Last fallback: Gemini free tier (slow).
- **Measured** from Dev's machine in India (gateway round trip 0.2–0.3 s), 12 runs per model, a
  Riley-style system prompt and one tool, time to first token:

  | Model | Reply p50 / p90 | Tool call p50 / p90 | ZIP tool call correct | Price in / out per 1M |
  | --- | --- | --- | --- | --- |
  | openai/gpt-4.1-nano | 0.76 / 1.32 s | 1.04 / 1.27 s | 12/12 | $0.10 / $0.40 |
  | google/gemini-3.1-flash-lite | 0.90 / 1.53 s | 1.02 / 1.39 s | 12/12 | $0.25 / $1.50 |
  | google/gemini-3.5-flash-lite | 0.94 / 1.98 s | 1.09 / 1.71 s | 12/12 | $0.30 / $2.50 |
  | openai/gpt-oss-120b | 1.15 / 2.65 s | 1.08 / 2.31 s | 12/12 | $0.10 / $0.50 |

  A first pass at 4 runs also tried `openai/gpt-4.1-mini` (one wrong tool call in four) and
  `google/gemma-4-31b-it` (fast replies, slow tool calls: 1.73 s p50); neither went further.
- **Why nano:** fastest on both p50 and p90, every tool call right, and cheapest, so the free credit
  covers the most calls (~550/month). The decision layer (code decides, the LLM extracts and speaks)
  means we don't need a bigger model's judgment. Re-check in the full pipeline at M1 and from
  LiveKit Cloud at M4; switching is one env var.
- **Temperature:** the "keep the default of 1" exception was specific to Gemini 3. With
  gpt-4.1-nano, CLAUDE.md section 4 applies again: low temperature.

## 2026-10-20: LLM through LiveKit Inference, not the Gemini free tier (approved by Dev)

- **Decision:** the LLM runs on LiveKit Inference (`inference.LLM`), paid from the Build plan's
  $2.50/month Inference credit. On Build the credit is a hard cap, so the cost stays $0. The model is
  chosen by a benchmark (time to first token, tool-call correctness) among cheap fast models.
  The Gemini free tier (Dev's own key) stays available as a fallback (it's slow).
  This overrides CLAUDE.md section 10 ("LiveKit Inference: avoid by default") for the LLM only;
  STT and TTS stay on Deepgram with Dev's key.
- **Why:** measured on 2026-10-20, the Gemini free tier took a median 16.3 s to first token on
  `gemini-3.5-flash-lite`, and `gemini-3.8-flash` mostly returned 503. Requesting the free Priority
  tier was silently downgraded to standard. The quality bar needs a total response ≤ 0.9 s p50.
- **Alternatives:** Groq free tier (fast, but free limits are visible only after sign-up, and the
  paid plan's 8K tokens/min is already tight for one call); Cerebras (needs a payment method on
  file, 5 requests/min); paid Gemini (breaks rule 2).
- **Consequence:** the credit covers roughly 150–550 calls a month depending on the model (about
  20 LLM requests × 2K tokens per call). The public page's daily cap (`MAX_SESSIONS_PER_DAY`) must
  fit that budget, and Riley must close politely if the credit runs out mid-month (M4).

## 2026-10-20: LiveKit Agent Skills installed for Claude Code

- **Decision:** `lk skills install --agent claude-code --skip-mcp` added LiveKit's seven skills to
  `.claude/skills/` (MIT, from `livekit/agent-skills`), recorded in `skills-lock.json`.
  `lk skills update` refreshes them.
- **Where they conflict with CLAUDE.md, CLAUDE.md wins:**
  - `building-livekit-agents` assumes LiveKit Inference for models. We use provider plugins with
    our own keys (section 10). The turn detector is the one Inference model we use (it has its own
    free allowance).
  - `debugging-livekit-agents` audio mode speaks test lines through LiveKit Inference TTS, which
    spends the $2.50/month credit. Default to text mode; use audio mode only for hearing bugs.
  - `running-livekit-simulations`: Build allows 350 text and 60 audio simulation turns a month
    (hard cap, no charge). Generating scenarios from source uploads our code to LiveKit; that's fine
    for this repo (no client material, no secrets in source).

## 2026-10-20: M1 model and audio choices (approved by Dev)

- **Turn detector:** `inference.TurnDetector()` (audio-based, LiveKit's current recommendation).
  Not the text `MultilingualModel` plugin, which is deprecated for 2.0. Free on Build: 7,500
  requests/month when self-hosted, unlimited when deployed to LiveKit Cloud, local `v1-mini` fallback
  at the cap.
- **Noise cancellation:** only models with no extra charge, ai-coustics `QUAIL_L` or Krisp NC,
  compared by listening at M1. Not `QUAIL_VF_S` (LiveKit's starter default), which costs extra.
- **Temperature:** Gemini's default of 1, per LiveKit's Gemini plugin docs (other values can cause
  looping on Gemini 3). This replaces "low LLM temperature" in CLAUDE.md section 4. Consistency
  comes from a short prompt, exact scripts from `business.yaml`, and gates; checked in M5.
- **Gemini model:** the fastest free-tier Flash model that handles tool calls well, chosen by
  measurement at M1. Start with `gemini-3.5-flash-lite` (Google: "our fastest ... 3.5 model") and
  compare with `gemini-3.8-flash`.
- **Free tier check:** Google's pricing page (updated 2026-10-19) lists every current Flash and
  Flash-Lite model as "Free of charge" on the free tier. The tier is set by the billing account of
  the key's Google Cloud project: a project with billing linked is "Paid" and gets charged. The
  key must come from a project whose Plan column in AI Studio says Free.

## 2026-10-20: LiveKit docs MCP server at project scope

- **Decision:** `livekit-docs` (`https://docs.livekit.io/mcp`) is registered in `.mcp.json`, committed
  with the repo.
- **Alternatives:** local scope (private to Dev's machine); the LiveKit Claude Code plugin (bundles the
  same server plus skills).
- **Reason:** anyone who opens the repo in Claude Code gets the same docs source that CLAUDE.md rule 6
  depends on. Claude Code asks once to approve a project-scoped server.

## 2026-10-20: business.yaml holds facts; gates hold rules; a test keeps it in sync

- **Decision:** `config/business.yaml` stores facts and thresholds (ZIPs, categories, fee, windows,
  exact scripts, urgency thresholds). The logic that combines them lives in `gates.py`.
  `tests/unit/test_business_config.py` fails if the YAML drifts from `docs/business.md`.
- **Alternatives:** encoding rules in YAML (a mini rule language); hand-copying with no check.
- **Reason:** rules in YAML are harder to test and read than plain Python, and a drift test makes
  "single source of truth" enforceable instead of a convention.

## 2026-10-20: Python 3.13, uv, exact pins

- **Decision:** `requires-python = ">=3.13,<3.14"`, `uv_build` backend with import name `agent`,
  direct dependencies pinned with `==` (`uv add --bounds exact`), and the full tree in `uv.lock`.
  CI runs `uv sync --locked`.
- **Alternatives:** a version range like LiveKit's starter (`livekit-agents~=1.8`).
- **Reason:** one interpreter version locally and in CI, and LiveKit Agents moves fast, so an
  unpinned minor bump should be a deliberate commit, not a surprise.
- **Versions at M0:** `livekit-agents` 1.8.8 (CLAUDE.md mentions the 1.5 line; PyPI and the docs are
  on 1.8, so the docs win per rule 6).

## 2026-10-20: Web calls first, phone second

- **Decision:** The primary channel is a public web-call page (Next.js on Vercel, LiveKit starter as the
  base) that visitors can use; the LiveKit phone number is secondary (M6).
- **Reason:** Free for visitors and for Dev (no international call costs), easier to share from the README
  and LinkedIn, and lower latency to show. Phone still proves SIP/telephony works.
- **Cost guard:** Turnstile, per-IP rate limits, a daily session cap, 5-minute calls and a busy state, since
  public visitors spend the same free quotas.

## 2026-10-20: Quality bar equals production Retell standard

- **Decision:** Measurable targets for latency, turn-taking, interruptions, speech, number
  normalization, recovery and endings (CLAUDE.md section 4), checked from M1 onward.
- **Reason:** The repo has to show the same quality Scaile AI ships on Retell, not a prototype.

## 2026-10-20: Phone number from LiveKit, not a Twilio SIP trunk

- **Decision:** Use LiveKit Phone Numbers (1 free US local number on the Build plan).
- **Alternatives:** Twilio number + SIP trunk into LiveKit.
- **Reason:** $0 and fewer moving parts. A Twilio SIP trunk is an optional stretch to demonstrate SIP
  trunk setup.

## 2026-10-20: Provider plugins with own keys, not LiveKit Inference

- **Decision:** Deepgram (STT, TTS) and Gemini (LLM) through plugins with our own API keys.
- **Reason:** LiveKit Inference credits on the free plan are small (~$2.50); Deepgram's $200 signup
  credit and Gemini's free tier last far longer.

## 2026-10-20: Python

- **Decision:** Python `livekit-agents`.
- **Reason:** Most mature SDK, turn detector and testing framework support, matches Dev's stack.

## 2026-10-20: LLM extracts, code decides

- **Decision:** All business decisions (safety, area, offered, urgency, readiness) live in pure Python
  gates; booking tools refuse to run without a passing readiness gate.
- **Reason:** Predictable, testable without an LLM, and resistant to prompt injection.
