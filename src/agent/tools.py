"""Riley's LLM tools: thin LiveKit wrappers around intake.py (CLAUDE.md section 6).

The LLM extracts facts and calls these; intake.py and gates.py decide. Each tool runs the pure
logic against this call's CallState (the session's userdata), then:
- enforces safety in code: on a hazard it plays the exact safety script and hangs up, with no LLM
  reply to paraphrase it;
- shortens endpointing when Riley's next question has a short answer (name, number, ZIP);
- does the calendar I/O for booking (off the event loop, with a filler line if it's slow);
- hands booked and callback leads to the CRM sender, which delivers them in the background;
- returns the gate's decision, `say` and `next_step` for the LLM to follow.
"""

import asyncio
import functools
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from livekit.agents import RunContext, function_tool, get_job_context
from livekit.agents.llm import ChatMessage, ToolError, Toolset

from agent import calendar, gates, intake, prompts
from agent.calendar import Calendar
from agent.config import REPO_ROOT, load_config
from agent.crm_client import CrmClient, LeadSender, Outbox, build_lead
from agent.gates import Decision, GateResult
from agent.state import CallState, Outcome

CONFIG = load_config()
TZ = ZoneInfo(CONFIG.timezone)
# Decisions and who ended the call are logged; what the caller said is not.
logger = logging.getLogger("riley")

# Enums in the tool schemas, built from business.yaml, so the LLM can't invent an id.
Category = Literal[tuple(CONFIG.offered) + tuple(CONFIG.not_offered)]  # type: ignore[valid-type]
SafetySignal = Literal[tuple(sorted(CONFIG.safety_signals))]  # type: ignore[valid-type]
VulnerableOccupant = Literal[tuple(sorted(CONFIG.vulnerable_occupants))]  # type: ignore[valid-type]
CallbackReason = Literal[tuple(sorted(CONFIG.callback_reasons))]  # type: ignore[valid-type]
Day = Literal[("today", "tomorrow", *CONFIG.booking.days)]  # type: ignore[valid-type]
PartOfDay = Literal[tuple(calendar.PARTS_OF_DAY)]  # type: ignore[valid-type]

# Endpointing: how long the turn detector may wait when it isn't sure the caller has finished.
# After a name or digits it often isn't, so it waited the full 2.5 s on 5 of 14 cloud turns.
# While Riley is collecting one of those, the wait drops to 1 s (Dev's decision, 2026-10-21).
DEFAULT_MAX_DELAY = 2.5  # the audio turn detector's documented default
SHORT_MAX_DELAY = 1.0
SHORT_ANSWER_FIELDS = frozenset({"first_name", "callback_number", "zip_code"})
# And the other way for digits: callers pause between groups ("eight zero one three nine ...
# two"), and a confident detector committed 0.3 s after the first group, splitting a ZIP across
# two turns (cloud call, 2026-10-22). Digit answers wait at least 0.6 s.
DEFAULT_MIN_DELAY = 0.3  # the audio turn detector's documented default
DIGITS_MIN_DELAY = 0.6
DIGIT_FIELDS = frozenset({"callback_number", "zip_code"})

# A calendar call slower than this gets the filler line (CLAUDE.md section 4: "more than about
# a second"). The acknowledgement has already covered the first moment.
FILLER_AFTER_SECONDS = 1.0


def endpointing_for(state: CallState) -> dict[str, float]:
    short = state.expecting in SHORT_ANSWER_FIELDS
    digits = state.expecting in DIGIT_FIELDS
    return {
        "min_delay": DIGITS_MIN_DELAY if digits else DEFAULT_MIN_DELAY,
        "max_delay": SHORT_MAX_DELAY if short else DEFAULT_MAX_DELAY,
    }


# --- Backends: the calendar and the CRM, one set per worker process ---------------------------


@dataclass
class Backends:
    calendar: Calendar
    leads: LeadSender


_backends: Backends | None = None


@dataclass
class Simulated:
    """A simulated call's own world: a fresh calendar, leads that are never sent, a fixed clock."""

    backends: Backends
    now: datetime


# Job id -> its simulated world. Keyed by job, not one process-wide override, because on
# Windows the SDK runs jobs as threads of one process (livekit-agents 1.8.8,
# _default_job_executor_type), and a simulation run has many calls going at once.
_simulated: dict[str, Simulated] = {}


def start_simulation(job_id: str, data: Path, at: datetime) -> None:
    """Under an agent simulation (main.py): this job's tools use a calendar in `data` holding
    only the weekly pattern, keep leads in a local outbox, and see the time as `at`. So every
    run of a scenario offers the same windows, and nothing reaches the real calendar."""
    _simulated[job_id] = Simulated(
        backends=Backends(
            calendar=Calendar(data / "calendar.sqlite3", CONFIG.booking, calendar.load_existing()),
            leads=LeadSender(CrmClient(None, Outbox(data / "outbox.sqlite3"))),
        ),
        now=at,
    )


def end_simulation(job_id: str) -> None:
    _simulated.pop(job_id, None)


def _simulation() -> Simulated | None:
    if not _simulated:  # every real call
        return None
    job = get_job_context(required=False)
    return _simulated.get(job.job.id) if job is not None else None


def backends() -> Backends:
    """Created on first use, from the environment (main.py loads .env first):
    DATA_DIR       where the SQLite files live (default: data/ in the repo)
    MOCK_CRM_URL   the CRM; unset means leads wait in the outbox (the deployed demo)
    CALENDAR_DELAY_SECONDS  demo switch: a slow calendar, to hear the filler line
    Tests replace _backends with temporary ones; a simulated call gets its own."""
    global _backends
    if (sim := _simulation()) is not None:
        return sim.backends
    if _backends is None:
        data = Path(os.getenv("DATA_DIR", REPO_ROOT / "data"))
        _backends = Backends(
            calendar=Calendar(
                data / "calendar.sqlite3",
                CONFIG.booking,
                calendar.load_existing(),
                delay_seconds=float(os.getenv("CALENDAR_DELAY_SECONDS", "0")),
            ),
            leads=LeadSender(
                CrmClient(os.getenv("MOCK_CRM_URL") or None, Outbox(data / "outbox.sqlite3"))
            ),
        )
    return _backends


async def drain_leads(timeout: float) -> None:
    """At hang-up: give background CRM deliveries a bounded time to finish (main.py)."""
    if _backends is not None:
        await _backends.leads.drain(timeout)


def now() -> datetime:
    """The business's local time. A function so tests can pin the clock; simulations pin it
    too (start_simulation)."""
    if (sim := _simulation()) is not None:
        return sim.now
    return datetime.now(TZ)


# --- Speaking from inside a tool ------------------------------------------------------------


def _say(context: RunContext[CallState], line: str, what: str) -> bool:
    """Say a fixed line now, without waiting for it to play. False if the session is closing."""
    try:
        context.session.say(line)
    except RuntimeError:
        # The session is already closing (cloud call, 2026-10-22: this raised and failed the
        # tool). These lines are niceties; the tool's result still matters.
        logger.info(f"skipped {what}: session closing")
        return False
    return True


def _acknowledge(context: RunContext[CallState]) -> None:
    """Say "Got it." now, once per caller turn, while the LLM writes the follow-up.

    A tool turn needs two LLM round trips (one to call the tool, one to reply) before any audio,
    and the model won't put text before its tool call. LiveKit's documented hold-message pattern:
    say() inside the tool, not awaited, plays while the rest of the turn is generated.
    """
    state = context.userdata
    if state.acknowledged:
        return
    state.acknowledged = True
    line = prompts.ACKNOWLEDGEMENTS[state.acks_said % len(prompts.ACKNOWLEDGEMENTS)]
    state.acks_said += 1
    state.ack_line = line if _say(context, line, "acknowledgement") else None


async def _calendar_call[T](context: RunContext[CallState], fn: Callable[..., T], *args: Any) -> T:
    """Run a calendar call off the event loop: SQLite blocks, and a blocked loop would stall the
    call's audio. If it's slow, Riley says the filler line so the caller isn't left in silence."""
    _acknowledge(context)
    task = asyncio.ensure_future(asyncio.to_thread(fn, *args))
    done, _ = await asyncio.wait({task}, timeout=FILLER_AFTER_SECONDS)
    if not done:
        _say(context, prompts.CHECKING_SCHEDULE, "filler line")
    return await task


def _caller_said(context: RunContext[CallState]) -> list[str]:
    """Everything the caller has said, this turn included: the SDK adds the caller's message to
    the history before any tool in that turn runs (livekit-agents 1.8.8)."""
    return [
        item.text_content or ""
        for item in context.session.history.items
        if isinstance(item, ChatMessage) and item.role == "user"
    ]


def _formatted_number(digits: str) -> str:
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


# --- From a decision to the tool's result -----------------------------------------------------


def _respond(context: RunContext[CallState], result: GateResult) -> dict[str, Any] | None:
    state, session = context.userdata, context.session
    if result.next_step == "say_exact_then_end_call":
        # Safety is enforced in code: the exact script, uninterruptible, then hang up. Returning
        # None means no LLM reply, so nothing can soften or reword it.
        logger.info("hanging up", extra={"by": "safety_script"})
        try:
            handle = session.say(CONFIG.safety_script, allow_interruptions=False)
        except RuntimeError:  # already closing: nothing more can be said
            return None
        handle.add_done_callback(lambda _: session.shutdown())
        return None
    _acknowledge(context)
    session.update_options(endpointing_opts=endpointing_for(state))
    out: dict[str, Any] = result.to_tool_output()
    if state.ack_line:
        # Right next to the reply being written, so the model doesn't open with another "Thanks."
        out["you_just_said"] = f"{state.ack_line} (already spoken; don't acknowledge again)"
    if result.next_step == "end_call":
        # A gate ended the call, so code hangs up, not the LLM: once Riley's reply to this result
        # has played, the session closes. Leaving it to end_call gave two goodbyes, or none and
        # an open line (behavior tests, 2026-10-21). LiveKit's EndCallTool uses the same hook.
        # The model still calls end_call after its goodbye in most runs (agent simulations,
        # 2026-10-25; renaming this step didn't change that). Harmless: no_second_goodbye
        # cues no reply, and the session closes once.
        logger.info("hanging up", extra={"by": "gate", "decision": result.decision.value})
        context.speech_handle.add_done_callback(lambda _: session.shutdown())
        out["say"] = (
            f"{result.say} Then say a short goodbye. The call ends by itself after your reply; "
            "don't call end_call."
        ).strip()
    if state.callback_number:
        out["callback_number_on_file"] = _formatted_number(state.callback_number)  # for read-back
    return out


async def _offer(
    context: RunContext[CallState],
    lead_in: GateResult,
    *,
    day: str | None = None,
    part_of_day: str | None = None,
    later: bool = False,
) -> dict[str, Any] | None:
    """Find open windows and offer up to two. lead_in's `say` goes first (a priority note, or
    "that window was just taken")."""
    state = context.userdata
    t = now()
    try:
        open_windows = await _calendar_call(context, backends().calendar.open_windows, t)
    except Exception:
        logger.exception("calendar unavailable")
        return _respond(context, intake.calendar_unavailable(state, CONFIG))
    pick = functools.partial(
        calendar.pick_windows, open_windows, CONFIG.booking, t, priority=state.priority
    )
    if day or part_of_day:
        asked, windows = "matching", pick(day=day, part_of_day=part_of_day)
        if not windows:
            asked, windows = "alternatives", pick()
    elif later and state.offered_windows:
        asked, windows = "later", pick(after_id=max(state.offered_windows))
    else:
        asked, windows = "first", pick()
    result = intake.offer_windows(state, CONFIG, windows, asked, t.date(), lead_in=lead_in.say)
    logger.info("windows offered", extra={"asked": asked, "windows": [w.id for w in windows]})
    out = _respond(context, result)
    if out is not None and windows:
        out["windows"] = [{"id": w.id, "when": state.offered_windows[w.id]} for w in windows]
    return out


async def _send_lead(state: CallState) -> None:
    """A booked call or a callback request: hand the lead to the background sender. Never fails
    the caller's turn; the outbox is the safety net."""
    window = None
    if state.outcome is Outcome.BOOKED and state.held_window:
        window = calendar.window_by_id(state.held_window, CONFIG.booking, now())
    key, payload = build_lead(state, window)
    try:
        await backends().leads.send(key, payload)
    except Exception:
        logger.exception("lead not stored", extra={"lead": key})


async def _run(
    context: RunContext[CallState],
    logic: Callable[..., GateResult],
    *,
    prepare: Callable[[], Awaitable[dict[str, Any]]] | None = None,
    offer: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Run one tool's logic. prepare: the tool's I/O, done first, its results passed to the
    logic. offer: filters for the windows if the logic says offer_windows."""
    state = context.userdata
    state.caller_turns = len(_caller_said(context))
    name = logic.__name__
    # A safety report always goes through: the script matters more than anything else.
    if logic is not intake.report_safety_hazard:
        if state.closing:
            # Riley is saying goodbye. A stray late turn (cloud call, 2026-10-22: "two." after an
            # out-of-area ZIP) must not change the record or start a new exchange.
            logger.info("tool ignored: call already decided", extra={"tool": name})
            return None
        if state.outcome is Outcome.BOOKED:
            return _respond(context, gates.already_booked(state))
    if prepare is not None:
        try:
            kwargs.update(await prepare())
        except Exception:
            logger.exception("calendar unavailable", extra={"tool": name})
            return _respond(context, intake.calendar_unavailable(state, CONFIG))
    before = state.outcome
    try:
        result = logic(state, CONFIG, **kwargs)
    except ValueError as e:  # an id the schema couldn't rule out; let the LLM correct it
        logger.info("tool rejected", extra={"tool": name, "error": str(e)})
        raise ToolError(str(e)) from e
    logger.info(
        "tool decision",
        extra={"tool": name, "decision": result.decision.value, "next_step": result.next_step},
    )
    if state.outcome is not before and state.outcome in (
        Outcome.BOOKED,
        Outcome.CALLBACK_REQUESTED,
    ):
        await _send_lead(state)
    if result.next_step == "offer_windows":
        return await _offer(context, result, **(offer or {}))
    return _respond(context, result)


# --- EndCallTool hooks (main.py) ---------------------------------------------------------------


async def end_call_requested(ev: Toolset.ToolCalledEvent) -> None:
    """EndCallTool hook: log that the model ended the call (the caller said they were done)."""
    logger.info("hanging up", extra={"by": "end_call"})


async def no_second_goodbye(ev: Toolset.ToolCompletedEvent) -> None:
    """EndCallTool hook: if a gate already ended the call, Riley has said goodbye; don't cue
    another. Returning no output means no reply, and the call ends after the current speech.
    A booked call isn't closing: Riley still says goodbye when the caller is done."""
    if ev.ctx.userdata.closing:
        ev.output = None


# --- The tools ---------------------------------------------------------------------------------


@function_tool
async def record_issue(
    context: RunContext[CallState],
    category: Category,
    symptoms: str,
    no_cooling_or_heat: bool,
    vulnerable_occupant: VulnerableOccupant | None = None,
    vulnerable_occupant_words: str | None = None,
    indoor_temp_f: int | None = None,
    safety_signals: list[SafetySignal] | None = None,
) -> dict[str, Any] | None:
    """Record what the caller needs, as soon as they describe the problem. Call again if it changes.

    Args:
        category: The service category that fits, from the list in your instructions.
        symptoms: The problem in a few words, in the caller's terms.
        no_cooling_or_heat: True if the system isn't cooling (or heating) the home at all,
            even if it runs: "stopped cooling", "blowing warm air", "no heat". False for
            noises, leaks, a blank thermostat, or weak but working cooling.
        vulnerable_occupant: Only if the caller says someone at home is 65 or older, an infant,
            or has a medical condition made worse by heat. Leave it out otherwise.
        vulnerable_occupant_words: The caller's exact words that say so, copied from what they
            said. Required with vulnerable_occupant; without them it isn't recorded.
        indoor_temp_f: The indoor temperature in Fahrenheit, only if the caller mentions it.
        safety_signals: Any hazard the caller mentions in the same breath.
    """
    # The model has invented a vulnerable occupant to fill the optional field (debugger call,
    # 2026-10-22), so intake.py checks the quoted words against what the caller really said.
    if vulnerable_occupant is not None:
        logger.info("vulnerable occupant claimed", extra={"occupant": vulnerable_occupant})
    return await _run(
        context,
        intake.record_issue,
        category=category,
        symptoms=symptoms,
        # Named for the model: as "not_working" it read an AC blowing warm air as working,
        # because it runs, and lost the priority (behavior test, 2026-10-22).
        not_working=no_cooling_or_heat,
        vulnerable_occupant=vulnerable_occupant,
        vulnerable_occupant_words=vulnerable_occupant_words,
        indoor_temp_f=indoor_temp_f,
        safety_signals=safety_signals or [],
        caller_said=_caller_said(context),
    )


@function_tool
async def record_caller_details(
    context: RunContext[CallState],
    first_name: str | None = None,
    callback_number: str | None = None,
) -> dict[str, Any] | None:
    """Record the caller's first name and/or callback number as soon as they say them.

    Pass the number exactly as you heard it, digits or words. If the caller corrects a detail,
    call this again with the corrected value. Leave out anything they haven't said; never guess
    or pass a placeholder such as "unknown".

    Args:
        first_name: The caller's first name.
        callback_number: The best number to call them back on, as heard.
    """
    return await _run(
        context,
        intake.record_caller_details,
        first_name=first_name,
        callback_number=callback_number,
    )


@function_tool
async def record_service_location(
    context: RunContext[CallState], zip_code: str
) -> dict[str, Any] | None:
    """Record the ZIP code where service is needed, as soon as the caller says it.

    Args:
        zip_code: The ZIP code exactly as you heard it, digits or words.
    """
    return await _run(context, intake.record_service_location, zip_code=zip_code)


@function_tool
async def report_safety_hazard(
    context: RunContext[CallState], signal: SafetySignal
) -> dict[str, Any] | None:
    """Call immediately, at any point in the call, if the caller mentions a smell of gas, a carbon
    monoxide alarm going off, a burning smell from the unit, sparks, or smoke.

    Don't say anything yourself first; the safety message plays automatically and ends the call.

    Args:
        signal: Which hazard the caller described.
    """
    return await _run(context, intake.report_safety_hazard, signal=signal)


@function_tool
async def request_callback(
    context: RunContext[CallState],
    reason: CallbackReason,
    first_name: str | None = None,
    callback_number: str | None = None,
) -> dict[str, Any] | None:
    """Arrange a callback from the team: the caller wants a person, has a billing question, asks
    about an existing appointment, has a complaint, or needs something you can't handle.

    Args:
        reason: Why they need a callback.
        first_name: The caller's first name, only if they've said it.
        callback_number: Their callback number as heard, only if they've said it.
    """
    return await _run(
        context,
        intake.request_callback,
        reason=reason,
        first_name=first_name,
        callback_number=callback_number,
    )


@function_tool
async def find_windows(
    context: RunContext[CallState],
    day: Day | None = None,
    part_of_day: PartOfDay | None = None,
) -> dict[str, Any] | None:
    """Find other appointment windows: when the caller asks for a particular day or time of
    day, or for something later than the windows you offered.

    Args:
        day: The day they asked for, only if they named one.
        part_of_day: Morning, afternoon or evening, only if they said.
    """
    later = day is None and part_of_day is None
    return await _run(
        context,
        intake.find_windows,
        offer={"day": day, "part_of_day": part_of_day, "later": later},
    )


@function_tool
async def choose_window(context: RunContext[CallState], window_id: str) -> dict[str, Any] | None:
    """Hold the window the caller picked, so you can read it back before booking. Call again if
    they change their mind.

    Args:
        window_id: The id of a window you offered, exactly as it appeared in the tool result.
    """
    state = context.userdata

    async def still_open() -> dict[str, Any]:
        t = now()
        windows = await _calendar_call(context, backends().calendar.open_windows, t)
        is_open = any(
            w.id == window_id and calendar.bookable(w, CONFIG.booking, t, state.priority)
            for w in windows
        )
        return {"still_open": is_open}

    return await _run(context, intake.choose_window, prepare=still_open, window_id=window_id)


@function_tool
async def book_appointment(context: RunContext[CallState]) -> dict[str, Any] | None:
    """Book the window the caller chose. Call only after you've read back their number and the
    window and they've said it's right."""
    # It writes a booking, so a barge-in mustn't stop it halfway (LiveKit's guidance for tools
    # that change data).
    context.disallow_interruptions()
    state = context.userdata

    async def book() -> dict[str, Any]:
        # The calendar is only touched once the booking gate allows it; intake.book_appointment
        # runs the same gate again to say why not.
        if gates.booking_gate(state, CONFIG).decision is not Decision.CONFIRMED:
            return {"booking": None}
        window_id = state.held_window or ""
        book_window = functools.partial(
            backends().calendar.book,
            key=calendar.booking_key(state.call_id, window_id),
            call_id=state.call_id,
            window_id=window_id,
            details={
                "first_name": state.first_name,
                "callback_number": state.callback_number,
                "zip_code": state.zip_code,
                "category": state.category,
                "symptoms": state.symptoms,
                "priority": state.priority,
            },
            now=now(),
            priority=state.priority,
        )
        try:
            booking = await _calendar_call(context, book_window)
        except calendar.WindowUnavailable:
            logger.info("window taken at booking", extra={"window": window_id})
            return {"booking": None}
        logger.info("booked", extra={"booking_id": booking.booking_id, "window": booking.window_id})
        return {"booking": booking}

    out = await _run(context, intake.book_appointment, prepare=book)
    if out is not None and out["decision"] == Decision.BOOKED.value:
        # The one line every booked caller must hear, so code says it rather than the model:
        # a caller who confirmed and said goodbye in one breath got only "Goodbye!" (agent
        # simulation, 2026-10-25).
        window = state.offered_windows.get(state.held_window or "", "")
        _say(context, prompts.BOOKED.format(window=window), "booking confirmation")
    return out


ALL_TOOLS = [
    record_issue,
    record_caller_details,
    record_service_location,
    report_safety_hazard,
    request_callback,
    find_windows,
    choose_window,
    book_appointment,
]
