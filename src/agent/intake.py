"""What each tool does: apply what the caller said to CallState, then run the gates.

Pure Python, no LiveKit: tools.py wraps these as LLM tools. Each function validates and normalizes
its input, writes it to the state, runs the gates in priority order (safety always first), settles
the call outcome when a gate ends the call, and returns the GateResult Riley follows.

Invalid ids raise ValueError; tools.py turns that into a ToolError the LLM can correct.
"""

from collections.abc import Iterable

from agent.config import BusinessConfig
from agent.gates import (
    Decision,
    GateResult,
    callback_gate,
    failed_attempt_gate,
    readiness_gate,
    safety_gate,
    service_area_gate,
    service_offered_gate,
    terminal_outcome,
    urgency_gate,
)
from agent.parsing import normalize_phone, normalize_zip
from agent.state import CallState, Outcome

# NOT_BOOKABLE carries the reason it can't be booked; each maps to the call's outcome.
_NOT_BOOKABLE_OUTCOMES = {
    "safety_signal": Outcome.SAFETY_REDIRECT,
    "out_of_area": Outcome.OUT_OF_AREA,
    "not_offered": Outcome.NOT_OFFERED,
}


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
    return result


def _miss(state: CallState, field: str, cfg: BusinessConfig) -> GateResult:
    state.failed_attempts[field] = state.failed_attempts.get(field, 0) + 1
    return _settle(state, failed_attempt_gate(state, field, cfg))


def _next(state: CallState, cfg: BusinessConfig) -> GateResult:
    """After any new fact: safety first, then whatever readiness says is next."""
    if state.callback_reason is not None:
        safety = safety_gate(state, cfg)
        if safety.decision is Decision.SAFETY_REDIRECT:
            return _settle(state, safety)
        return _settle(state, callback_gate(state, cfg))
    return _settle(state, readiness_gate(state, cfg))


def record_caller_details(
    state: CallState,
    cfg: BusinessConfig,
    first_name: str | None = None,
    callback_number: str | None = None,
) -> GateResult:
    if first_name and first_name.strip():
        state.first_name = first_name.strip()
    if callback_number is not None:
        number = normalize_phone(callback_number)
        if number is None:
            return _miss(state, "callback_number", cfg)
        state.callback_number = number
        state.failed_attempts.pop("callback_number", None)
    return _next(state, cfg)


def record_service_location(state: CallState, cfg: BusinessConfig, zip_code: str) -> GateResult:
    zip5 = normalize_zip(zip_code)
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
) -> GateResult:
    if category not in cfg.offered and category not in cfg.not_offered:
        raise ValueError(f"unknown category {category!r}")
    state.category = category
    if symptoms and symptoms.strip():
        state.symptoms = symptoms.strip()
    state.not_working = not_working
    if vulnerable_occupant in cfg.vulnerable_occupants:
        state.vulnerable_occupant = vulnerable_occupant
    if indoor_temp_f is not None:
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
) -> GateResult:
    state.callback_reason = reason if reason in cfg.callback_reasons else "other"
    return record_caller_details(state, cfg, first_name=first_name, callback_number=callback_number)
