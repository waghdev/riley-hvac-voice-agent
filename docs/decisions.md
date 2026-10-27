# Decision log

One entry per decision: date, decision, alternatives considered, reason. Newest at the top.

## 2026-10-27: LiveKit Inference first, the Gemini free tier as fallback (Dev approved)

- **Decision:** Riley's LLM is LiveKit's `llm.FallbackAdapter` over two models
  (`main.build_llm`, `main.with_fallback`): `google/gemini-3.1-flash-lite` on LiveKit
  Inference, paid from the Build plan's $2.50 monthly credit, then `gemini-3.5-flash-lite` on
  the Gemini free tier with Dev's key. When Inference refuses (the credit runs out mid-month),
  the request goes to the free tier and the call carries on. `LLM_MODEL` and
  `LLM_FALLBACK_MODEL` set them; locally `.env` has `LLM_MODEL=gemini-3.5-flash-lite` and no
  fallback, so testing never spends the credit callers need.
- **Why this route:** it costs $0. Gemini paid was the other option: Dev's Google AI Pro plan
  includes $10 a month of Cloud credit that Google says covers the Gemini API, but Google asks
  for a ₹500 (about $5) prepayment before credits apply, and Dev preferred LiveKit. The plan's
  higher limits apply only inside the AI Studio web app, not to API keys. On Inference, Gemini
  3.1 Flash Lite gets 100 requests a minute, not 15, and measured 1,409 ms p50 in the Oct 25
  audio run. Build allowances reset on the 1st of each calendar month and don't roll over
  (quotas docs), so the credit is back on Nov 1; until then every request falls back.
- **How the fallback behaves (installed source, livekit-agents 1.8.8), defaults kept:**
  - One attempt per model: a refusal moves on at once. If both fail, the session's own
    retries rerun the pair (3 more times), as they retried the single model before.
  - The failed model is marked unavailable and checked in the background after each turn
    until it answers. `build_llm` runs per call, so every call starts on Inference again.
  - No switch once a reply has started streaming, so the caller never hears two half replies.
  - **Rule 6 note:** the fallback docs say the session gets an error event when a fallback
    triggers. In 1.8.8 it doesn't: the failed model's error goes to that model, and the
    session only listens to the adapter, which reports an error only when both fail. That
    matters here: `close_on_fatal_error` hangs up on an unrecoverable error, so if the session
    heard the covered failure, Riley would hang up on a call the free tier was carrying.
    `tests/unit/test_build_llm.py` pins it with stand-in models, so an SDK upgrade that
    changes it fails a test.
- **Testing stays on the free tier:** the behavior suite runs on `gemini-3.5-flash-lite` (the
  fallback model), paced under 15 requests a minute. The primary model passed the same suite on
  Inference in M3 and M5, and audio simulations on the deployed agent test it once the credit
  is back. Text simulations against the deployed agent spend the credit after the reset, so
  they stay few; against a local agent they can't be paced under 15 a minute.
- **Public page:** 4 calls a day (from 5). At about 1.5 cents a call that's up to ~120 calls
  (~$1.80) a month, leaving room for simulations and Dev's checks. One live call at a time
  until the reset, since until then every call is on the free tier; on Nov 1, two. The footer
  says replies come from Google Gemini, and from Gemini's free tier when the credit runs out.
  The Vercel overrides of `CALLS_PER_DAY` and `MAX_LIVE_CALLS` were removed, so the tested
  defaults in `web/lib/gatekeeper.ts` are the only values.
- **The two bugs from the audio run, each pinned by tests first (rule 7):**
  - **A name must be one the caller gave** (`parsing.name_heard`): every word of it said by
    the caller, whole or spelled out ("D. A. N. A."), and none of them a word for someone
    else (mom, wife, landlord...). The model saved "mom" from "my eighty one year old mom is
    here". A rejected name isn't saved and isn't a miss: Riley asks for it as usual.
  - **"Mm-hmm" doesn't choose between two windows** (`parsing.only_assent`,
    `intake.choose_window`): with two on offer, a choice needs a caller turn since the offer
    that says more than a hum or "okay, that works". Otherwise the tool returns
    `NO_WINDOW_CHOSEN` and Riley asks which. One window offered: "mm-hmm" takes it. Words
    before the offer don't count, and a pick followed by "yes" still does. The list is only
    assent words, so "either is fine", "the first one" and any time pass.
- **Checked on the deployed agent (out-of-area text simulation, `smoke.yaml`), which found a
  bug the local tests couldn't, since locally there's no fallback:**
  - **First run failed:** every fallback request came back 400, "Manually set deadline 5s is
    too short. Minimum allowed deadline is 10s." The adapter's default `attempt_timeout` (5 s)
    reaches Google as the request deadline. Fixed with `attempt_timeout=10.0`, pinned by a
    test; second run passed (out_of_area, final state right).
  - **The free tier is slow at times:** in the passing call, two requests ran past the 10 s
    deadline (504) and were retried, so the caller waited about 10 s twice. Google won't take
    a shorter deadline. This is how every call goes until Nov 1, and afterwards only once the
    credit runs out.
  - **The exhausted credit isn't a clean "no":** Inference refuses in 20-40 ms, but its
    background check sometimes succeeds (the gateway let a few requests through), so Riley
    flips back to it and the next request pays one fast refusal. Build caps are hard, so
    nothing can be billed.
- **Behavior suite on this code: 19 passed, 5 stopped at the judge.** The judge's model
  (`gemini-3.5-flash`, which Google reports as `gemini-3.6-flash`) has a free-tier limit of
  **20 requests a day**, and today's earlier runs had used it. In all five, Riley's own
  assertions before the judge passed: the full intake recorded name, number and ZIP through
  the new name check, and "the twelve to two one works" chose the window. The judged checks
  re-run after the daily reset.

## 2026-10-27: Riley's LLM on the Gemini free tier with our own key (Dev approved)

- **Decision:** `LLM_MODEL=gemini-3.5-flash-lite` through the Google plugin (`google.LLM`) with
  `GOOGLE_API_KEY`, on Google AI Studio's free tier. A `provider/model` id still routes to
  LiveKit Inference (`main.build_llm`), so going back when the Build credit resets is one setting.
  Only the LLM changes: LiveKit Cloud, Deepgram and Riley's code stay as they are. Back in line
  with CLAUDE.md section 10 (own keys, not Inference).
- **Why:** the $2.50 Inference credit ran out on 2026-10-26 and can't carry testing and visitors.
  Groq's free tier (8K tokens a minute, 200K a day) can't carry one call: Riley sends ~2,300
  tokens a request before history, ~25-50K a minute. Cerebras is a 5-requests-a-minute trial.
  The Gemini free tier, 16 s to first token at M0, now answers Riley's real intake quickly.
- **Measured (2026-10-27, from India):** Riley's full intake through the plugin, 12 requests:
  time to first token p50 1.31 s, p90 1.90 s (prompt ~2,950 tokens with history, 0 reasoning
  tokens at the default thinking level, so nothing to turn off). `gemini-3.1-flash-lite` on the
  free tier was erratic (1.7-56 s).
- **Free-tier limit, from Google's 429:** 15 requests a minute per project per model
  (`GenerateRequestsPerMinutePerProjectPerModel-FreeTier`). No daily limit hit yet (over 250
  requests on 2026-10-27). One call's busiest minute in the Oct 25 audio run used 11-12 requests
  (counted from the transcript, leaving out lines code says), so **the page takes one live call
  at a time** (`MAX_LIVE_CALLS=1` in `web/lib/gatekeeper.ts` and Vercel).
- **Behavior suite:** 24/24, judged by `gemini-3.5-flash` (`gemini-3.8-flash` timed out on every
  free-tier request). A run is 147 requests (139 Riley, 8 judge), so it must be paced under 15 a
  minute; unpaced, 11 tests failed on 429s alone. The Gemini API has no `parallel_tool_calls`
  switch; the suite's one-goodbye test still passes.
- **Rule 3:** the free tier may use prompts to improve Google's models. The page already asks for
  made-up details next to the Call button; the footer now says where replies come from and that.
- **Deployed:** `GOOGLE_API_KEY` and `LLM_MODEL` added to the agent's secrets (temporary file,
  deleted after; the CLI adds keys without touching the others).
- **Audio run on the deployed agent (us-east, 3 scenarios, 20 audio turns): 1 passed. Stopped
  for Dev's decision (rule 8).**
  - **One call alone hit the per-minute limit.** About a minute into the clicking-noise call,
    15 requests came back 429; after the SDK's retries the error handler said "trouble on my
    end" and hung up before the booking. Transcript counts miss what also spends the limit:
    cancelled preemptive generations and every retry. 15 a minute can't carry even one call
    reliably.
  - Latency (agent records, 19 turns): total p50 1,720 ms, p90 9,143 ms (Inference on Oct 25:
    1,409 / 2,565); the p90 is the retries. Simulator, caller-heard: p50 2,038, p95 11,259 ms.
  - The paused-number fix works in audio: "Six zero two. Five five. Five, O one four eight" was
    recorded as 602-555-0148, in both calls that gave one.
  - `gemini-3.5-flash-lite` invented tool arguments: ZIP 85001 twice and 602-555-1234 (refused
    by `digits_heard`, so Riley asked again), and "mom" as the caller's first name from "my
    eighty one year old mom is here" (saved: names have no evidence check yet). It also took
    "Mhmm" as a choice between two windows; the read-back caught it. Both are bugs to pin with
    tests whichever LLM Riley ends on.

## 2026-10-25: M5 evals: LiveKit Agent Simulations, graded on final state (Dev approved)

- **Runner:** LiveKit Agent Simulations, not a home-grown runner. LiveKit's simulator plays the
  caller from a YAML script and an LLM judges the transcript, on the Build plan's free
  allowance (350 text and 60 audio turns a month; a turn is one caller message, so the core
  suite is about 50). A home-grown runner would have spent the $2.50 LLM credit on the
  simulated caller and the judge, and couldn't measure audio.
- **Sets:** `tests/scenarios/core.yaml` (the nine flows in CLAUDE.md section 9 plus a number
  corrected at the read-back, each with an expected final state), `guardrails.yaml` (price
  pressure, prompt injection) and `audio.yaml` (pauses, barge-in, backchannels; audio mode,
  deployed agent). Point-form personas (PERSONA / OPENING LINE / FACTS / DO, IN ORDER) keep
  the simulated caller on script.
- **Final-state grading:** the judge only reads the transcript, so `main.check_final_state`
  (`on_simulation_end`) compares the call's `CallState` with the scenario's
  `userdata.expected` (`scenarios.final_state_failure`: outcome, window, number, priority,
  category, callback reason; any booking on a call that didn't end booked) and fails the run
  on a difference. Confirmed both ways with a scenario that expected the wrong outcome.
- **Deterministic world:** under a simulation (`ctx.simulation_context()`), each call gets a
  fresh calendar with only the weekly pattern and a clock pinned to Wednesday 2026-10-21
  9:30 Phoenix, so windows are the same every run; no CRM. Keyed by job id, not set
  process-wide, because on Windows livekit-agents runs jobs as threads of one process.
  Real calls never take that branch.
- **SDK limits found (1.8.8), worked around in simulation only:**
  - The simulator collects `on_simulation_end`'s verdict over a link that closes with the
    session, so when Riley hung up, a wrong final state never reached it. In a simulation,
    a hang-up checks the final state first: right, it hangs up as in production (the judge
    sees the real ending); wrong, the line stays open and Riley stops answering, so the
    simulator ends the call and the check fails the run. Leaving the line open every time
    made the judge fail right endings (the caller kept talking to a silent Riley).
  - `session.start` connects the room in parallel with the greeting. With no audio to wait
    for, a text simulation's greeting could reach the room first ("cannot access local
    participant before connecting"), so simulations connect first.
  - Several local text simulations at once on Windows stalled (thread executor, TLS setup
    blocking the loop) and one hit an FFI panic. Local runs use `--concurrency 1`.
- **QA grader (`qa/grade_call.py`, `qa/rubric.yaml`):** reads an exported run. Deterministic
  checks first (greeting and disclosure, booking only after an answered read-back, nothing
  booked after a closing gate, the exact safety script after a hazard, no price but $89 and
  the free estimate, turn length and style), then a Gemini free-tier rubric (accuracy,
  clarity, empathy, efficiency; critical / major / minor). Free tier because grading is
  offline, so its 10 to 50 s replies don't matter, and every caller is fictional (rule 3).
  - The model reasons through the call before it scores: with scores first, every model tried
    gave 5/5/5/5 to everything. On a deliberately bad call `gemini-3.5-flash-lite` found the
    ignored infant in 95-degree heat (critical) and the re-asked name (major).
  - It is lenient on borderline calls (it passed "Got it. Goodbye!" after a booking, which
    LiveKit's judge flagged), so the checks and LiveKit's judge carry the hard failures.
- **Fixes found by simulations, each pinned by a test first:** booking confirmation said by
  code ("You're all set for..."), after a caller confirmed and said goodbye in one breath and
  heard only "Goodbye!"; no promising service before the gates; the read-back says it isn't
  booked yet; fees can't be waived; the transcript (web page and simulations) gets the same
  acknowledgement and name guards as TTS; the acknowledgement guard waits for a name.
- **Known and left:** Riley calls `end_call` after a gate's goodbye in most runs, though the
  result says not to (renaming the step didn't help). Harmless: code hangs up once and no
  second goodbye is cued. "I can help with that" before the ZIP check still slips through in
  about 1 in 10 behavior runs (from 1 in 3).
- **Audio run (deployed agent, us-east, 3 scenarios, 24 of 60 audio turns): 2 passed.**
  - Caller-heard latency p50 1,579 ms, p95 2,578 ms (the simulator measures what the caller
    hears). The agent's own records for the same 25 turns: total p50 1,409 / p90 2,565 ms;
    end of utterance 457 / 1,004; STT 291; LLM first token 479; TTS 131. Web target is
    900 / 1,400: not met, the same gap Dev accepted at M2 (1,231 / 2,635).
  - Turn-taking: 1 end-of-turn misprediction, 0.3% overlapping speech, no false interruptions,
    no unanswered turns. Entity recall 100% both ways.
  - The failure was the worst bug M5 found: a number given in paused groups was cut at the
    first pause, Riley talked over the rest, and the model recorded 602-501-4200 from eight
    digits, read it back and booked it (the final-state check failed the run). Fixed in code:
    a number must be made of digits the caller said (`parsing.digits_heard`), and Riley waits
    for the rest of a partial number (`turns.DigitHold`). Also fixed: the booking
    confirmation said twice (`RepeatedConfirmationGuard`). Unit-tested, not yet re-run in
    audio.
- **LiveKit Inference credit exhausted (2026-10-26).** The gateway refuses with
  `inference_quota_exceeded` until the next billing cycle; Build caps are hard, so nothing was
  billed. M5's testing used it up: about 25 full or partial behavior-suite runs plus
  repeated single tests (measuring flaky behavior), 164 text-simulation turns (Riley's own
  LLM calls are billed even though the simulator's are not) and the audio run. Riley's live
  LLM is on the same credit, so the deployed demo can't hold a conversation until it resets:
  callers hear the greeting, then the pre-rendered "trouble on my end" line and a hang-up.
  Dev decides what's next (rule 2).

## 2026-10-25: Page redesign (Dev's request), and only the Call button asks for a token

- **Bug (Dev's first visit to the live page):** "We couldn't confirm you're human" showed before
  he pressed Call. `useSession` fetches tokens by itself (livekit components-react source): once
  on mount to warm up the connection (`prepareConnection`), and again when a call ends, to have
  the next one ready. Those requests reached `/api/token` with no Turnstile token, were refused,
  set the message, and spent the visitor's Turnstile token.
- **Fix:** `web/lib/call-token-source.ts` lets exactly one request through per press of Call.
  The hook's own fetches get a promise that never settles: the hook doesn't wait on them (the
  warm-up only logs a warning on failure, and the prefetch isn't awaited), so nothing hangs,
  nothing reaches the endpoint, and nothing is logged. Unit-tested. The page does its own warm-up
  without a token: `room.prepareConnection(LIVEKIT_URL)` covers DNS, TLS and the region lookup.
  Checked on the live site with headless Chrome: no `/api/token` request on page load.
- **Design (Dev asked for "a voice orb, links and graphics"):**
  - The starter's Aura shader orb is the hero. It idles, pulses once the visitor can call, and
    spins up while connecting; the same orb reacts to Riley's voice in the call view.
  - Cool/warm glows and a faint grid behind the content: heating and cooling.
  - Capability cards (only things Riley does today), a "how a turn works" pipeline, and Dev's
    GitHub and LinkedIn links.
  - The Aura component is licensed Polyform Non-Resale (Unicorn Studio), not MIT. Fine for a
    demo; credited in `web/README.md`.
  - Checked at 1440 px and on a Pixel 7 profile.

## 2026-10-25: M4 web call page (design approved by Dev)

- **Page:** LiveKit's `agent-starter-react` (Next.js, MIT) in `web/`, imported unchanged in one
  commit so every change shows as a diff. Not LiveKit Cloud's hosted embed widget: its only
  protection is an allowed-origins list (a script can send any Origin), with no bot check,
  rate limit or daily cap, and it would show none of this engineering.
- **Token endpoint (`web/app/api/token/route.ts`), server-side only.** `lib/gatekeeper.ts` is a
  pure function with its I/O passed in (the same pattern as the Python gates). The checks, in
  order:
  1. Turnstile, so bots never touch a counter.
  2. Fewer than 4 live rooms. Asked of LiveKit, since Build allows 5 at once, which leaves one
     for testing. Being busy doesn't use up a visitor's calls.
  3. 3 calls per visitor per hour.
  4. 5 calls a day. The $2.50 LLM credit covers about 220 calls a month, shared with testing.

  Refusals are 403 (bot) or 429, and missing config or a failing dependency is a 503, failing
  closed because every call costs quota. The room name (`kestrel-web-<random>`) and the agent
  dispatch are set on the server and never taken from the browser. Tokens live 2 minutes,
  enough to join; LiveKit refreshes them after that.
- **Counters:** Upstash Redis (free, 500K commands a month, no card), fixed windows per UTC hour
  and day, each window its own key. Visitors are keyed by an HMAC of their IP (keyed with the
  LiveKit secret), never the IP. Vercel's one free firewall rule (Hobby) is an outer flood guard:
  10 requests a minute per IP on `/api/token`. Its API returns "not found" until the project's
  first deployment, so it's added after that.
- **Token source:** `TokenSource.literal(fn)`, a fresh request for every call. `custom` and
  `endpoint` cache the token until it expires, and a cached token could rejoin a deleted room
  (recreating it and dispatching Riley again) without passing the checks.
- **Voice only:** no chat input, camera or screen share. Typed messages would spend the same
  LLM credit, and the page is meant to feel like a phone call.
- **Greeting latency from the browser:** the page times "room connected → Riley speaking"
  (and "Call button → speaking"), shows it, and sends it to the agent on the
  `riley.client_timing` text stream. The agent validates it as untrusted input and logs it as a
  `client_greeting` record, and `latency_report.py` reports it. "Speaking" is the agent's state
  attribute, so the time includes that update reaching the browser.
- **When a model fails for good** (for example the LLM credit runs out), Riley plays a
  pre-rendered "trouble on my end" line and hangs up. Rule 6 note: LiveKit's docs say an
  unrecoverable error closes the session, but 1.8.8 closes only after 3 in a row
  (`max_unrecoverable_errors`), so the documented say-only pattern left dead air in a debugger
  call with a broken model name. The handler hangs up itself.
- **Checked against the real project:** a token from the local endpoint joined a fresh room, and
  the deployed Riley was dispatched by name and arrived immediately. Over curl: no Turnstile
  token gave 403, three calls were admitted, the fourth got 429.
- **Vercel:** project `riley-kestrel-comfort`, root `web/`, functions in `iad1` (US East, near the
  agent), and builds skipped when a push doesn't touch `web/`. Vercel's GitHub app can't see the
  private repo, so deploys go through the CLI until Dev grants it access. Secrets go from `.env`
  to Vercel through the CLI, never through chat.
- **Small choices:** `web/.gitattributes` keeps LF line endings, because the starter's Prettier
  rule failed on Windows checkouts. `web/` is excluded from the agent's Docker image. A CI job
  lints, format-checks, tests and builds the page.

## 2026-10-22: A fact the model claims must be in the caller's words (vulnerable occupant)

- **Found:** in the debugger, "my AC stopped cooling, it's blowing warm air" was recorded with
  `vulnerable_occupant="infant"` in 1 of 5 runs (with `indoor_temp_f: 0` in the same call: the
  model filling every optional field). That made the call priority, which unlocks same-day
  windows.
- **Decision:** `record_issue` takes `vulnerable_occupant_words`, the caller's exact words, and
  `intake.py` keeps the occupant only if those words appear in what the caller said
  (`parsing.said_by_caller`: case and punctuation ignored, whole words). An invented quote isn't in
  the transcript, so the claim is dropped. The LLM still extracts; code verifies, then decides.
- **Alternatives:** a stronger prompt or docstring (the docstring already said "only if the caller
  says"); an explicit "none" enum value (makes the right answer easier, guarantees nothing);
  keyword lists per occupant type (miss real phrasings like "my mom's 82"). Raising a ToolError on
  a failed check would let the model retry with a made-up quote and cost a round trip, so the claim
  is dropped and logged instead.
- **Same session:** `not_working` was false 3 of 3 times for "stopped cooling, blowing warm air,
  95 in here": the model read a running AC as working. The parameter the model sees is now
  `no_cooling_or_heat`, with examples (18 of 18 right after); the state field keeps its name.
- **Not done yet:** a made-up indoor temperature (other than 0, which is already ignored) would
  also make a call priority. Not seen so far; the same check would apply if it shows up.

## 2026-10-22: M3 booking and CRM, as built (design approved by Dev)

Dev approved the six design calls before the build; these are those, plus the smaller choices made
along the way.

- **Where leads go:** the deployed agent has no CRM to reach (the mock CRM runs on Dev's PC), so
  its leads wait in the outbox, with a log line. `mock_crm` runs locally for tests and demos.
  A free Cloudflare quick tunnel can point the cloud agent at it when an end-to-end demo is wanted.
- **Bookings in SQLite, not JSON:** each call runs in its own process, and two calls taking the
  last place in a window would race on a JSON file. `BEGIN IMMEDIATE` makes "count, then insert"
  atomic across processes. Other customers' appointments are a weekly pattern in
  `config/mock_calendar.json`, so the schedule looks real. In the cloud the files live in the
  container and reset on each deploy, which is fine for a demo.
- **Business facts added (business.md):** two appointments per window (two technicians), windows
  up to 6 days ahead (so a weekday name is never ambiguous), same-day windows for priority calls
  only and at least 60 minutes out (this is what makes a priority call different), and a booked
  appointment isn't changed on the same call (the caller can call back).
- **Read-back in code:** `booking_gate` allows a booking only when readiness passes, a window
  offered on this call is held, and the caller has spoken after a read-back of exactly that number
  and window. "Spoken after" is counted from `session.history`. The 1.8.8 source adds the caller's
  message to the history before that turn's tools run (`agent_activity.py`), in tests and on calls
  alike. Whether the caller said yes is the LLM's call; that the read-back happened, and was
  answered, is code's.
- **Fewer round trips:** when the details are complete, the tool result already carries two open
  windows, so Riley offers them in the same reply.
- **Tools:** `find_windows` (a day, a part of day, or "later"), `choose_window` (ids from this call's
  offers only), `book_appointment` (calls `disallow_interruptions()`, LiveKit's guidance for tools
  that write data). After booking, other tools answer "already booked" instead of changing it;
  a safety report still goes through.
- **CRM delivery:** outbox first, then POST with an `Idempotency-Key` (the booking's key, so the
  calendar and the CRM dedupe the same way). Up to 4 attempts with capped exponential backoff and
  full jitter (0.5, 1, 2 s caps); 5xx, 408, 429 and network errors retry, other 4xx are marked
  rejected. httpx (already installed via google-genai) because `MockTransport` and
  `ASGITransport` test it with no network; FastAPI + uvicorn for the mock, in a dependency group
  that stays out of the agent image.
- **Callbacks send a lead too:** otherwise "a team member will call you back" goes nowhere.
- **At hang-up:** deliveries in flight get 7 s, in a shutdown callback. Deleting the room starts the
  job's shutdown by itself, and LiveKit kills the process about 10 s later
  (`shutdown_process_timeout`), so a step after `delete_room()` could be cut off silently. Leads
  are usually long delivered by then; anything cut off stays pending in the outbox.
- **Filler line:** calendar calls run in a worker thread (SQLite blocks; a blocked event loop
  stalls the call's audio). If one takes over 1 s, Riley says "One sec, checking the schedule."
  after the "Got it.". `CALENDAR_DELAY_SECONDS` makes the calendar slow for a demo.
- **Calendar down:** any calendar error offers a callback instead of failing the turn.
- **Speech:** "between 12-2 pm" is now said "between noon and two", not "noon to two" (found while
  writing the README trace).
- **Checked end to end** in the text-mode debugger, against the local mock CRM set to fail twice:
  500, 500, 201, one lead stored, outcome `booked`, one goodbye, clean shutdown.

## 2026-10-22: M2 closed with the measured latency gap accepted (Dev's decision)

- **Measured (6 cloud calls, us-east, web):** total response p50 1,231 ms, p90 2,635 ms, against
  targets of 900 / 1,400 ms. Later turns p50 1,119 ms. First caller turns p50 2,572 ms: 4 of 6 sat
  at the 2.5 s endpointing cap. The cause isn't confirmed; it didn't recur in a seventh call with
  debug logs (444 ms end of utterance), and Dev uses headphones, so ambience leaking into the mic
  is ruled out.
- **Decision:** Dev listened to the calls: "I don't feel any latency... the agent responds
  quickly". The gap stays on the record (rule 8), and the README will report the real numbers.
  M5 re-measures it with the web page and the scenario runner.
- **Two fixes from the seventh call:** digit answers (number, ZIP) wait at least 0.6 s before the
  turn commits, because a confident detector split "eight zero one three nine ... two" into two
  turns at 0.3 s; and tools are no-ops once the outcome is decided (except a safety report), so a
  stray late turn can't rewrite the record while Riley says goodbye.

## 2026-10-21: M2 as built: what the prompt asks for, and what code enforces

Every rule below was tried in the prompt first wherever possible; each one that the model
(gemini-3.1-flash-lite, default temperature) didn't follow reliably moved into code, with a test.

- **Safety (code):** `report_safety_hazard`, or a hazard passed to `record_issue`, makes the tool
  play the exact safety script (uninterruptible) and hang up when it ends. The tool returns
  nothing, so there's no LLM reply that could reword it.
- **Gate-ended calls (code):** out of area, not offered, callback taken, or a number that couldn't
  be caught twice. The tool hangs up after Riley's one reply (shutdown when the tool's speech
  handle completes, the same hook `EndCallTool` uses). Leaving it to the model produced two
  goodbyes, or none and an open line. `end_call` cues no goodbye once a gate has ended the call.
- **Short answers (code):** `max_delay` is 1.0 s while Riley waits for a name, number or ZIP, and
  2.5 s otherwise; it resets on every caller turn. Measured in the audio pipeline: the phone-number
  turn's end of utterance went from ~2,500 ms to 1,002 ms (detector probability 0.35 against a
  0.36 threshold).
- **Spoken acknowledgement (code):** tool turns need two LLM round trips before any audio, and the
  model won't put text before its tool call. The tool says a rotating "Got it." / "Okay." /
  "Thanks." (once per caller turn) while the reply is written, following LiveKit's documented
  hold-message pattern. First audio on tool turns: 3.1–3.3 s → 1.8–2.0 s on Dev's PC.
  The reply still opened with "Thanks." in 2 of 2 runs despite the prompt and a tool-result field,
  so `LeadingAckGuard` drops a leading acknowledgement before TTS.
- **Caller's name (code):** `NameGuard` keeps the first vocative use and drops later ones before
  TTS; read-back mentions stay.
- **Numbers (code):** `speak_numbers_stream` before TTS; the transcript keeps digits.
- **Model quirks (code):** placeholder arguments ("unknown", "N/A") count as not given; indoor
  temperatures outside 40–140°F (the model passed 0) are ignored.
- **Prompt:** ~460 words (persona, how to follow `say`/`next_step`, allowed prices, categories).
- **Known gap:** the TTS-only guards don't change the transcript, which still shows the model's
  words (a second "Thanks.", a repeated name). The M4 web page shows a live transcript; revisit
  with a transcription-node transform if it reads badly there.

## 2026-10-21: M2 structure: one agent with tools, gates in pure Python (approved by Dev)

- **Decision:** a single `Riley` agent with a small set of tools. Each tool validates its input,
  writes `CallState`, runs the relevant gates in `gates.py` and returns the `GateResult` to the LLM.
  Booking refuses in code unless the readiness gate passed. Safety is checked on every tool call,
  and a dedicated tool reports a hazard the moment the caller mentions one.
- **Why:** LiveKit's workflow guide says to start with one agent and a small set of tools, and to
  split only on a concrete limitation (prompt bloat, conflicting tool access, multi-turn collection
  needing its own loop, backtracking). Riley has about six tools, no conflicting permissions, and a
  correction is just the same tool called again. It's also the lowest-latency option.
- **Alternatives:** supervisor with tasks (more structure, some latency per task); a task group for
  intake (built-in backtracking, but rigid when callers give details out of order). Revisit only if
  measurements show one of the limitations above.
- **Schema:** `CallState` (call id, first name, 10-digit callback number, 5-digit ZIP, category,
  symptoms, not-working flag, indoor temperature, vulnerable occupant, safety signals, failed
  attempts per field, outcome); `GateResult(decision, reason, say, next_step)`. Two additions to
  CLAUDE.md's gate table: readiness returns `NOT_BOOKABLE` (not just `MISSING`) when the caller is
  out of area, the service isn't offered or a safety signal exists; and a retry rule turns a second
  failed attempt at the same detail into `callback_requested` (section 4).

## 2026-10-21: Short-answer endpointing gets fixed in M2, with context (Dev's decision)

- **Measured:** on the deployed agent, normal turns totalled 757–1,260 ms, but 5 of 14 turns sat at
  exactly ~2.5 s of end-of-utterance delay: the audio turn detector wasn't confident after a name
  or a digit string, so it waited its full `max_delay`.
- **Decision:** close M1 with the gap recorded. In M2, Riley's tools and `CallState` know which
  detail she just asked for, so `max_delay` drops to about 1 s while she's collecting a name,
  callback number or ZIP (`session.update_options(endpointing_opts=...)`, documented for runtime
  changes) and returns to 2.5 s for open answers.
- **Alternatives:** lower `max_delay` on every turn (rejected: it would cut off callers who pause
  mid-sentence, which section 4 forbids); Deepgram Flux end-of-turn detection (kept as an option if
  the context-aware change isn't enough).

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
