"""What each tool does: apply what the caller said to CallState, then run the gates.

Pure Python, no LiveKit: tools.py wraps these as LLM tools. Each function validates and normalizes
its input, writes it to the state, runs the gates in priority order (safety always first), settles
the call outcome when a gate ends the call, and returns the GateResult Riley follows.

Invalid ids raise ValueError; tools.py turns that into a ToolError the LLM can correct.
"""

from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import date

from agent.calendar import Booking, Window
from agent.config import BusinessConfig
from agent.gates import (
    Decision,
    GateResult,
    booked,
    booking_gate,
    calendar_down,
    callback_gate,
    failed_attempt_gate,
    readiness_gate,
    safety_gate,
    service_area_gate,
    service_offered_gate,
    terminal_outcome,
    urgency_gate,
    which_window,
    window_taken,
    windows_gate,
)
from agent.parsing import (
    digits_heard,
    name_heard,
    normalize_phone,
    normalize_zip,
    only_assent,
    said_by_caller,
)
from agent.state import CallState, Outcome, ReadBack

# NOT_BOOKABLE carries the reason it can't be booked; each maps to the call's outcome.
_NOT_BOOKABLE_OUTCOMES = {
    "safety_signal": Outcome.SAFETY_REDIRECT,
    "out_of_area": Outcome.OUT_OF_AREA,
    "not_offered": Outcome.NOT_OFFERED,
}


# What LLMs put in an argument they don't have a value for (debugger call, 2026-10-21: the
# model called request_callback(first_name="unknown", callback_number="unknown")).
_PLACEHOLDERS = frozenset({"unknown", "n/a", "na", "none", "null", "not provided", "not given"})
INDOOR_TEMP_RANGE_F = (40, 140)  # anything outside this isn't a reading a caller would give


def _given(value: str | None) -> str | None:
    """The value, stripped, or None if it's empty or a placeholder rather than something said."""
    if value is None or not value.strip() or value.strip().lower() in _PLACEHOLDERS:
        return None
    return value.strip()


def _settle(state: CallState, result: GateResult) -> GateResult:
    """Record the outcome if this decision ends the call, and what Riley will ask next."""
    outcome = terminal_outcome(result.decision)
    if result.decision is Decision.NOT_BOOKABLE:
        outcome = _NOT_BOOKABLE_OUTCOMES.get(result.reason.split(":")[0])
    elif result.decision is Decision.OFFER_CALLBACK and result.next_step == "end_call":
        outcome = Outcome.INCOMPLETE  # no usable number, so no callback either
    if outcome is not None:
        state.outcome = outcome
    state.expecting = (
        result.next_step.removeprefix("ask:") if result.next_step.startswith("ask:") else None
    )
    if result.decision is Decision.READ_BACK and state.callback_number and state.held_window:
        # Riley's reply to this result is the read-back, so the caller's answer comes in a
        # later turn; booking_gate waits for it.
        state.read_back = ReadBack(state.callback_number, state.held_window, state.caller_turns)
    return result


def _miss(state: CallState, field: str, cfg: BusinessConfig) -> GateResult:
    state.failed_attempts[field] = state.failed_attempts.get(field, 0) + 1
    return _settle(state, failed_attempt_gate(state, field, cfg))


def _next(state: CallState, cfg: BusinessConfig) -> GateResult:
    """After any new fact: safety first, then whatever readiness says is next. Once a window is
    held, that's the booking gate: a changed number gets read back again."""
    if state.callback_reason is not None:
        safety = safety_gate(state, cfg)
        if safety.decision is Decision.SAFETY_REDIRECT:
            return _settle(state, safety)
        return _settle(state, callback_gate(state, cfg))
    ready = readiness_gate(state, cfg)
    if ready.decision is Decision.READY_TO_BOOK and state.held_window is not None:
        return _settle(state, booking_gate(state, cfg))
    return _settle(state, ready)


def _heard(digits: str | None, caller_said: Sequence[str] | None) -> str | None:
    """The digits, if the caller said them (parsing.digits_heard); None means "ask again".
    caller_said None skips the check (tests of other logic); tools.py always passes it."""
    if digits is None or caller_said is None or digits_heard(digits, caller_said):
        return digits
    return None


def record_caller_details(
    state: CallState,
    cfg: BusinessConfig,
    first_name: str | None = None,
    callback_number: str | None = None,
    caller_said: Sequence[str] | None = None,
) -> GateResult:
    first_name, callback_number = _given(first_name), _given(callback_number)
    # A name the caller didn't give ("mom", parsing.name_heard) is left out, not counted as a
    # miss: the caller hasn't failed to give it, so Riley just asks for it.
    if first_name is not None and (caller_said is None or name_heard(first_name, caller_said)):
        state.first_name = first_name
    if callback_number is not None:
        number = _heard(normalize_phone(callback_number), caller_said)
        if number is None:
            return _miss(state, "callback_number", cfg)
        state.callback_number = number
        state.failed_attempts.pop("callback_number", None)
    return _next(state, cfg)


def record_service_location(
    state: CallState, cfg: BusinessConfig, zip_code: str, caller_said: Sequence[str] | None = None
) -> GateResult:
    zip5 = _heard(normalize_zip(zip_code), caller_said)
    if zip5 is None:
        return _miss(state, "zip_code", cfg)
    state.zip_code = zip5
    state.failed_attempts.pop("zip_code", None)
    safety = safety_gate(state, cfg)
    if safety.decision is Decision.SAFETY_REDIRECT:
        return _settle(state, safety)
    area = service_area_gate(state, cfg)
    if area.decision is Decision.OUT_OF_AREA:
        return _settle(state, area)
    return _next(state, cfg)


def record_issue(
    state: CallState,
    cfg: BusinessConfig,
    category: str,
    symptoms: str,
    not_working: bool = False,
    vulnerable_occupant: str | None = None,
    indoor_temp_f: int | None = None,
    safety_signals: Iterable[str] = (),
    vulnerable_occupant_words: str | None = None,
    caller_said: Sequence[str] = (),
) -> GateResult:
    """caller_said: everything the caller has said on this call, to check the LLM's evidence
    for a vulnerable occupant against (it makes them up; see parsing.said_by_caller)."""
    if category not in cfg.offered and category not in cfg.not_offered:
        raise ValueError(f"unknown category {category!r}")
    state.category = category
    if symptoms and symptoms.strip():
        state.symptoms = symptoms.strip()
    state.not_working = not_working
    if vulnerable_occupant in cfg.vulnerable_occupants and said_by_caller(
        vulnerable_occupant_words, caller_said
    ):
        state.vulnerable_occupant = vulnerable_occupant
    # A real indoor reading, not a placeholder: the LLM has passed 0 for "not mentioned".
    if (
        indoor_temp_f is not None
        and INDOOR_TEMP_RANGE_F[0] <= indoor_temp_f <= INDOOR_TEMP_RANGE_F[1]
    ):
        state.indoor_temp_f = indoor_temp_f
    state.safety_signals |= set(safety_signals) & cfg.safety_signals

    safety = safety_gate(state, cfg)
    if safety.decision is Decision.SAFETY_REDIRECT:
        return _settle(state, safety)
    offered = service_offered_gate(state, cfg)
    if offered.decision is Decision.NOT_OFFERED:
        return _settle(state, offered)

    urgency = urgency_gate(state, cfg)
    state.priority = urgency.decision is Decision.PRIORITY
    result = _next(state, cfg)
    if state.priority:
        result = GateResult(
            result.decision, result.reason, f"{urgency.say} {result.say}".strip(), result.next_step
        )
    return result


def report_safety_hazard(state: CallState, cfg: BusinessConfig, signal: str) -> GateResult:
    if signal not in cfg.safety_signals:
        raise ValueError(f"unknown safety signal {signal!r}")
    state.safety_signals.add(signal)
    return _settle(state, safety_gate(state, cfg))


def request_callback(
    state: CallState,
    cfg: BusinessConfig,
    reason: str,
    first_name: str | None = None,
    callback_number: str | None = None,
    caller_said: Sequence[str] | None = None,
) -> GateResult:
    state.callback_reason = reason if reason in cfg.callback_reasons else "other"
    return record_caller_details(
        state, cfg, first_name=first_name, callback_number=callback_number, caller_said=caller_said
    )


# --- Booking. tools.py does the calendar I/O and passes in what it found; these decide. --------


def offer_windows(
    state: CallState,
    cfg: BusinessConfig,
    windows: Sequence[Window],
    asked: str,
    today: date,
    lead_in: str = "",
) -> GateResult:
    """Offer the windows calendar.pick_windows found. `lead_in` goes first: a priority note, or
    "that window was just taken"."""
    for w in windows:
        state.offered_windows[w.id] = w.when(today)
    if windows:  # with none found, the windows offered before are still the choice
        state.latest_offer = [w.id for w in windows]
        state.offered_at_turn = state.caller_turns
    result = windows_gate(state, cfg, found=len(windows), asked=asked)
    return _settle(state, replace(result, say=f"{lead_in} {result.say}".strip()))


def calendar_unavailable(state: CallState, cfg: BusinessConfig) -> GateResult:
    """The calendar failed: offer a callback instead of leaving the caller stuck."""
    return _settle(state, calendar_down())


def find_windows(state: CallState, cfg: BusinessConfig) -> GateResult:
    """The caller wants another day or time: let go of any held window and offer again."""
    state.held_window = None
    return _next(state, cfg)


def choose_window(
    state: CallState,
    cfg: BusinessConfig,
    window_id: str,
    still_open: bool,
    caller_said: Sequence[str] | None = None,
) -> GateResult:
    """Hold the window the caller picked; booking_gate then asks for the read-back.

    caller_said: everything the caller has said on this call. Between two windows, a choice
    needs a caller turn since the offer that says more than "mm-hmm" or "okay"
    (parsing.only_assent); the model has picked one for a caller who only said "Mhmm.". None
    skips the check (tests of other logic); tools.py always passes it."""
    if window_id not in state.offered_windows:
        raise ValueError(f"unknown window_id {window_id!r}; use the id of a window you offered")
    if (
        caller_said is not None
        and len(state.latest_offer) > 1
        and all(only_assent(turn) for turn in caller_said[state.offered_at_turn :])
    ):
        return _settle(state, which_window())
    if not still_open:
        state.held_window = None
        return _settle(state, window_taken(window_id))
    state.held_window = window_id
    return _next(state, cfg)


def book_appointment(state: CallState, cfg: BusinessConfig, booking: Booking | None) -> GateResult:
    """The result of a booking attempt. tools.py only calls the calendar when booking_gate says
    CONFIRMED; `booking` is None if it didn't, or if the window was taken meanwhile."""
    gate = booking_gate(state, cfg)
    if gate.decision is not Decision.CONFIRMED:
        return _settle(state, gate)
    if booking is None:
        taken = state.held_window or ""
        state.held_window = None
        return _settle(state, window_taken(taken))
    state.booking_id = booking.booking_id
    return _settle(state, booked(state))
