# Decision log

One entry per decision: date, decision, alternatives considered, reason. Newest at the top.

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
