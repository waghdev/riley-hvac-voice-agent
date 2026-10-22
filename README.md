# voice-agent-reference

A production-style AI phone agent built on an open-source real-time pipeline (LiveKit Agents),
for a fictional HVAC company. Call it, and it qualifies you, handles safety situations, and books
a service appointment.

> Status: in progress. Sections marked TODO fill in as milestones land.

## Try it

TODO: "Talk to Riley" link to the public web-call page (works in any browser, no phone needed).
Phone number for live testing, if kept active.

## Demo

TODO: 60 to 90 second video of a real call.

## What it does

TODO: one paragraph and the outcomes table (booked, safety redirect, out of area, not offered,
callback, incomplete).

## Architecture

TODO: Mermaid diagram (web page and token endpoint, caller, LiveKit number, room, agent worker, STT/LLM/TTS, gates, tools, mock CRM).

## Latency (measured)

TODO: p50/p90 per stage, web vs phone, number of calls and turns, what dominates and what was tuned.

| Stage | p50 | p90 |
| --- | --- | --- |
| End of utterance | | |
| STT final | | |
| LLM first token | | |
| TTS first audio | | |
| Total response | | |

## The decision layer

**The LLM extracts, code decides, the LLM speaks the decision.** Riley never decides whether a
ZIP is served, a service is offered, a call is urgent or an appointment can be booked. She calls a
tool with what the caller said; the tool normalizes it, writes it to `CallState`, and runs pure
Python gates that return a decision plus what to say next.

A real turn (text-mode debugger):

```text
Caller: my AC stopped cooling completely, and my mom who's 80 lives with me
  -> record_issue(category="ac_repair", no_cooling_or_heat=true,
                  vulnerable_occupant="age_65_plus",
                  vulnerable_occupant_words="my mom who's 80 lives with me")
  <- {decision: MISSING, next_step: "ask:first_name",
      say: "Let them know you'll treat this as a priority visit. Ask for their first name."}
Riley:  Got it. I'm sorry to hear that. I've noted that this is a priority... May I have your
        first name?
```

Every gate is a pure function of `(CallState, BusinessConfig)`, table-tested without an LLM:

```python
def readiness_gate(state: CallState, cfg: BusinessConfig) -> GateResult:
    """READY_TO_BOOK only if eligible and complete. Booking refuses to run without it."""
    safety = safety_gate(state, cfg)
    if safety.decision is Decision.SAFETY_REDIRECT:
        return GateResult(Decision.NOT_BOOKABLE, safety.reason, safety.say, safety.next_step)
    if state.zip_code is not None and state.zip_code not in cfg.zip_codes:
        ...  # out of area: never bookable, whatever the caller or the model says
```

Where the model wasn't reliable, the rule moved into code, each with a test:

- **Safety:** a gas smell, CO alarm, burning smell, sparks or smoke plays the exact safety script
  and hangs up. There's no LLM reply to reword it.
- **Ending calls:** a gate that ends the call hangs up after Riley's one reply, so there's no
  double goodbye and no open line.
- **Short answers:** the turn detector waits at most 1 s, not 2.5 s, while Riley collects a name,
  number or ZIP.
- **Speech:** numbers are spoken the way people say them ("six oh two, five five five..."), the
  caller is addressed by name at most once, and a spoken "Got it." covers the tool's round trip.
- **Evidence:** the model once filled an optional field with an invented "infant", making a call
  priority. Now it must pass the caller's own words, and code checks them against the
  transcript; an invented quote isn't there, so the claim is dropped.

Code: [`gates.py`](src/agent/gates.py), [`intake.py`](src/agent/intake.py),
[`tools.py`](src/agent/tools.py), [`spoken.py`](src/agent/spoken.py). Decisions and the
measurements behind them: [`docs/decisions.md`](docs/decisions.md).

## Booking and CRM

Booking follows the same pattern: the model picks up what the caller wants, code decides whether
it may happen. A real booking from the text-mode debugger, against the local mock CRM set to fail
twice:

```text
Caller: the first one works
  -> choose_window(window_id="2026-10-23T12:00")
  <- {decision: READ_BACK, next_step: "confirm_booking", say: "Read back their callback number,
      602-555-0142, and the window, tomorrow, 12-2 pm, and ask if that's all right."}
Riley (as spoken): Okay. One sec, checking the schedule. Just to confirm, I have you down
        for a visit tomorrow between noon and two in the afternoon, and I'll reach you at
        six oh two, five five five, oh one four two. Does that sound right?
Caller: yes, that's right
  -> book_appointment()
  <- {decision: BOOKED, say: "Tell them they're booked for tomorrow, 12-2 pm, then ask if
      there's anything else."}
  .. CRM: 500, 500, 201 (same Idempotency-Key each time; one lead stored)
```

- **Read-back in code:** `book_appointment` refuses unless the details are complete and eligible,
  a window offered on this call is held, and the caller has spoken since a read-back of exactly
  that number and window. Booking in the same turn as the read-back, or after a corrected number,
  is refused. A model talked into "just book it" can't skip it.
- **No double bookings:** bookings live in SQLite, and "count, then insert" runs under a write lock,
  because each call is its own process. The key (call id + window) makes a retried booking find
  the first one.
- **Leads that aren't lost or sent twice:** each lead is written to a local outbox before any
  network call, then sent in the background with an `Idempotency-Key`. Server errors and timeouts
  are retried (4 attempts, capped exponential backoff, full jitter). Anything still failing stays
  in the outbox for `scripts/redeliver_outbox.py`. The caller never waits on the CRM.
- **No dead air:** a calendar call slower than a second gets "One sec, checking the schedule."
  If the calendar fails outright, Riley offers a callback instead.

The mock CRM ([`mock_crm/app.py`](mock_crm/app.py)) runs locally and can be told to fail
(`POST /control {"fail_next": 2}`). The deployed demo has no CRM to reach, so its leads wait in the
outbox. Code: [`calendar.py`](src/agent/calendar.py), [`crm_client.py`](src/agent/crm_client.py).

## Testing

TODO: unit, behavior and scenario layers, how to run them, and the call-quality grader.

## Retell vs a custom pipeline

TODO: link to docs/retell-vs-custom.md (written from production experience).

## Run it yourself

TODO: prerequisites, `.env`, `uv sync`, run locally, connect a phone number.

## Built by

Devendra (Dev) Wagh, Co-Founder & CTO at Scaile AI. Built with Claude Code.

## Credits

- Keyboard typing sounds (Riley's "thinking" sound): "keyboard typing" by Anton,
  https://freesound.org/s/137/, licensed CC BY 4.0. Bundled with LiveKit Agents.
- Office ambience: bundled with LiveKit Agents.
