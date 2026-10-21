"""Everything Riley has learned on a call, and how it ended. Pure data: no LiveKit, no network.

Tools write it (after validating input); gates read it and decide. One CallState per call.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class Outcome(StrEnum):
    """Every call ends in exactly one of these (CLAUDE.md section 3)."""

    BOOKED = "booked"
    SAFETY_REDIRECT = "safety_redirect"
    OUT_OF_AREA = "out_of_area"
    NOT_OFFERED = "not_offered"
    CALLBACK_REQUESTED = "callback_requested"
    INCOMPLETE = "incomplete"


@dataclass
class CallState:
    call_id: str
    first_name: str | None = None
    callback_number: str | None = None  # ten digits, from parsing.normalize_phone
    zip_code: str | None = None  # five digits, from parsing.normalize_zip
    category: str | None = None  # a service id from business.yaml, offered or not
    symptoms: str | None = None  # one line, in the caller's terms
    not_working: bool = False  # no cooling (AC, heat pump) or no heat (furnace)
    indoor_temp_f: int | None = None  # only if the caller mentioned it
    vulnerable_occupant: str | None = None  # one of business.yaml urgency.vulnerable_occupants
    safety_signals: set[str] = field(default_factory=set)  # ids from business.yaml safety.signals
    priority: bool = False  # set by the urgency gate; M3's booking offers the earliest window
    failed_attempts: dict[str, int] = field(default_factory=dict)  # field -> misses so far
    callback_reason: str | None = None
    outcome: Outcome | None = None
    # Conversation control, not business facts. `expecting`: the detail Riley just asked for, so
    # endpointing can be shortened for short answers (a name, a number, a ZIP). `acknowledged`:
    # whether this caller turn already got a spoken "Got it." (main.py resets it each turn);
    # `acks_said` rotates the wording.
    expecting: str | None = None
    acknowledged: bool = False
    acks_said: int = 0
