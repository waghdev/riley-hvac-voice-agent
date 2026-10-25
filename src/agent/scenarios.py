"""Agent simulations: the time a scenario happens at, and the check on how a call ended.

LiveKit's simulator plays a caller from tests/scenarios/*.yaml and an LLM judges the transcript.
A transcript can read well while the call ended wrong (booked an out-of-area caller, booked the
wrong window), so main.py also compares the final CallState with the scenario's
`userdata.expected` here, and fails the run on any difference. Pure: no LiveKit, no network.
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from agent.state import CallState, Outcome

# Every scenario happens at this moment unless its userdata says `now`: a Wednesday morning,
# business time. Scenarios name windows as dates, so the clock has to stay put for them to keep
# matching (writing-livekit-scenarios skill: pin the clock).
SIMULATION_NOW = "2026-10-21T09:30"

# What a scenario can expect, and how to read it off the call's final state.
CHECKS = {
    "outcome": lambda s: (s.outcome or Outcome.INCOMPLETE).value,
    "priority": lambda s: s.priority,
    "window": lambda s: s.held_window if s.booking_id else None,
    "callback_number": lambda s: s.callback_number,
    "callback_reason": lambda s: s.callback_reason,
    "category": lambda s: s.category,
}


def scenario_now(userdata: dict[str, Any], tz: ZoneInfo) -> datetime:
    """The scenario's `now` (local business time, ISO without offset), else SIMULATION_NOW."""
    return datetime.fromisoformat(userdata.get("now", SIMULATION_NOW)).replace(tzinfo=tz)


def final_state_failure(expected: dict[str, Any] | None, state: CallState) -> str | None:
    """Why the call's final state doesn't match the scenario, or None if it does.

    Only the keys a scenario lists are compared, plus one rule for every scenario: a call that
    didn't end booked must not have made a booking.
    """
    expected = expected or {}
    problems = []
    if unknown := sorted(set(expected) - set(CHECKS)):
        # A misspelled key would otherwise check nothing and pass.
        problems.append(f"unknown expected keys {unknown}")
    for key, want in expected.items():
        if key in CHECKS and (got := CHECKS[key](state)) != want:
            problems.append(f"{key}: expected {want!r}, got {got!r}")
    if state.booking_id and state.outcome is not Outcome.BOOKED:
        problems.append(f"booking {state.booking_id} made, but the call ended {state.outcome}")
    return "; ".join(problems) or None
