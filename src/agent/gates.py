"""The decision layer: every business decision is a pure function of (CallState, BusinessConfig).

The LLM extracts facts and speaks; these functions decide (CLAUDE.md section 6). Each returns a
GateResult that a tool hands back to the LLM: `say` is a short instruction for Riley's next line,
`next_step` tells her (and main.py) what comes next. No LiveKit, no network, no LLM.

next_step values:
    continue                  carry on collecting details
    ask:<field>               ask for that field next (main.py shortens endpointing for it)
    offer_windows             everything checks out; move to scheduling
    take_callback_details     switch to taking a callback request
    end_call                  say the closing line, then end the call
    say_exact_then_end_call   say `say`'s quoted script word for word, then end the call
"""

from dataclasses import dataclass
from enum import StrEnum

from agent.config import BusinessConfig
from agent.state import CallState, Outcome


class Decision(StrEnum):
    CLEAR = "CLEAR"
    SAFETY_REDIRECT = "SAFETY_REDIRECT"
    IN_AREA = "IN_AREA"
    OUT_OF_AREA = "OUT_OF_AREA"
    INVALID_ZIP = "INVALID_ZIP"
    OFFERED = "OFFERED"
    NOT_OFFERED = "NOT_OFFERED"
    PRIORITY = "PRIORITY"
    STANDARD = "STANDARD"
    READY_TO_BOOK = "READY_TO_BOOK"
    MISSING = "MISSING"
    NOT_BOOKABLE = "NOT_BOOKABLE"
    ASK_AGAIN = "ASK_AGAIN"
    OFFER_CALLBACK = "OFFER_CALLBACK"
    CALLBACK_READY = "CALLBACK_READY"


@dataclass(frozen=True)
class GateResult:
    decision: Decision
    reason: str  # machine-readable, for logs and tests: "zip_not_served:85301"
    say: str  # what Riley should get across next ("" = nothing in particular)
    next_step: str

    def to_tool_output(self) -> dict[str, str]:
        """What the LLM sees as the tool's result."""
        return {
            "decision": self.decision.value,
            "say": self.say,
            "next_step": self.next_step,
        }


# How Riley refers to each field when asking for it.
FIELD_LABELS = {
    "first_name": "first name",
    "callback_number": "best callback number",
    "zip_code": "ZIP code where service is needed",
    "category": "kind of service they need",
    "symptoms": "a short description of the problem",
}

_TERMINAL = {
    Decision.SAFETY_REDIRECT: Outcome.SAFETY_REDIRECT,
    Decision.OUT_OF_AREA: Outcome.OUT_OF_AREA,
    Decision.NOT_OFFERED: Outcome.NOT_OFFERED,
    Decision.CALLBACK_READY: Outcome.CALLBACK_REQUESTED,
}


def terminal_outcome(decision: Decision) -> Outcome | None:
    """The call outcome a decision settles, if it ends the call."""
    return _TERMINAL.get(decision)


def safety_gate(state: CallState, cfg: BusinessConfig) -> GateResult:
    """Overrides everything: gas, CO alarm, burning smell, sparks or smoke, at any point."""
    signals = sorted(state.safety_signals & cfg.safety_signals)
    if signals:
        return GateResult(
            Decision.SAFETY_REDIRECT,
            reason="safety_signal:" + ",".join(signals),
            say=f'Say exactly: "{cfg.safety_script}"',
            next_step="say_exact_then_end_call",
        )
    return GateResult(Decision.CLEAR, reason="no_safety_signal", say="", next_step="continue")


def service_area_gate(state: CallState, cfg: BusinessConfig) -> GateResult:
    if state.zip_code is None:
        return GateResult(
            Decision.INVALID_ZIP,
            reason="zip_unreadable",
            say="Ask for the five-digit ZIP code again, in a different way.",
            next_step="ask:zip_code",
        )
    if state.zip_code in cfg.zip_codes:
        return GateResult(
            Decision.IN_AREA, reason=f"zip_served:{state.zip_code}", say="", next_step="continue"
        )
    return GateResult(
        Decision.OUT_OF_AREA,
        reason=f"zip_not_served:{state.zip_code}",
        say=(
            f"Apologize: we only serve {cfg.service_area}. Don't suggest other companies. "
            "Then say a short goodbye."
        ),
        next_step="end_call",
    )


def service_offered_gate(state: CallState, cfg: BusinessConfig) -> GateResult:
    if state.category in cfg.offered:
        return GateResult(
            Decision.OFFERED, reason=f"offered:{state.category}", say="", next_step="continue"
        )
    what = cfg.not_offered.get(state.category or "", "that service")
    return GateResult(
        Decision.NOT_OFFERED,
        reason=f"not_offered:{state.category}",
        say=(
            f"Apologize: {what.lower()} isn't something we handle; we do residential heating "
            "and cooling. Don't suggest other companies. Then say a short goodbye."
        ),
        next_step="end_call",
    )


def urgency_gate(state: CallState, cfg: BusinessConfig) -> GateResult:
    """PRIORITY per business.md's urgency rule; everything else is STANDARD."""
    vulnerable = state.vulnerable_occupant in cfg.vulnerable_occupants
    hot_inside = (
        state.indoor_temp_f is not None and state.indoor_temp_f >= cfg.indoor_temp_priority_f
    )
    no_cooling = state.category in cfg.no_cooling_categories and state.not_working
    no_heat = state.category in cfg.no_heat_categories and state.not_working

    if no_cooling and vulnerable:
        reason = f"no_cooling_and_vulnerable:{state.vulnerable_occupant}"
    elif no_cooling and hot_inside:
        reason = f"no_cooling_and_indoor_temp:{state.indoor_temp_f}"
    elif no_heat and vulnerable:
        reason = f"no_heat_and_vulnerable:{state.vulnerable_occupant}"
    else:
        return GateResult(Decision.STANDARD, reason="standard", say="", next_step="continue")
    return GateResult(
        Decision.PRIORITY,
        reason=reason,
        say="Let them know you'll treat this as a priority visit.",
        next_step="continue",
    )


def _has(value: str | None) -> bool:
    return bool(value and value.strip())


def readiness_gate(state: CallState, cfg: BusinessConfig) -> GateResult:
    """READY_TO_BOOK only if eligible and complete. Booking refuses to run without it."""
    safety = safety_gate(state, cfg)
    if safety.decision is Decision.SAFETY_REDIRECT:
        return GateResult(Decision.NOT_BOOKABLE, safety.reason, safety.say, safety.next_step)
    if state.zip_code is not None and state.zip_code not in cfg.zip_codes:
        area = service_area_gate(state, cfg)
        return GateResult(Decision.NOT_BOOKABLE, "out_of_area", area.say, area.next_step)
    if state.category is not None and state.category not in cfg.offered:
        offered = service_offered_gate(state, cfg)
        return GateResult(Decision.NOT_BOOKABLE, "not_offered", offered.say, offered.next_step)

    present = {
        "first_name": _has(state.first_name),
        "callback_number": state.callback_number is not None
        and len(state.callback_number) == cfg.callback_number_digits,
        "zip_code": state.zip_code is not None,
        "category": state.category is not None,
        "symptoms": _has(state.symptoms),
    }
    missing = [f for f in cfg.required_fields if not present.get(f, False)]
    if missing:
        return GateResult(
            Decision.MISSING,
            reason="missing:" + ",".join(missing),
            say=f"Ask for their {FIELD_LABELS[missing[0]]}.",
            next_step=f"ask:{missing[0]}",
        )
    return GateResult(
        Decision.READY_TO_BOOK,
        reason="all_required_fields",
        say="Read back the callback number to confirm it, then move on to scheduling.",
        next_step="offer_windows",
    )


def failed_attempt_gate(state: CallState, field: str, cfg: BusinessConfig) -> GateResult:
    """After a detail didn't come through: ask again once, then stop looping (section 4)."""
    misses = state.failed_attempts.get(field, 0)
    if misses < cfg.max_attempts_per_field:
        return GateResult(
            Decision.ASK_AGAIN,
            reason=f"retry:{field}:{misses}",
            say=f"Ask for their {FIELD_LABELS.get(field, field)} again, in a different way.",
            next_step=f"ask:{field}",
        )
    if field == "callback_number" or state.callback_number is None:
        # Without a usable number there's no callback to take.
        return GateResult(
            Decision.OFFER_CALLBACK,
            reason=f"gave_up:{field}:{misses}",
            say=(
                "Apologize that you couldn't catch it, and invite them to call back when it's "
                "convenient. Then say a short goodbye."
            ),
            next_step="end_call",
        )
    return GateResult(
        Decision.OFFER_CALLBACK,
        reason=f"gave_up:{field}:{misses}",
        say="Apologize that you couldn't catch it, and offer to have a team member call them back.",
        next_step="take_callback_details",
    )


def callback_gate(state: CallState, cfg: BusinessConfig) -> GateResult:
    """A callback request needs a name and a number; then Riley promises the callback."""
    for field, ok in (
        ("first_name", _has(state.first_name)),
        ("callback_number", state.callback_number is not None),
    ):
        if not ok:
            return GateResult(
                Decision.MISSING,
                reason=f"callback_missing:{field}",
                say=f"Ask for their {FIELD_LABELS[field]}.",
                next_step=f"ask:{field}",
            )
    return GateResult(
        Decision.CALLBACK_READY,
        reason=f"callback:{state.callback_reason or 'other'}",
        say=f"Read back the callback number, then tell them {cfg.callback_promise}.",
        next_step="end_call",
    )
