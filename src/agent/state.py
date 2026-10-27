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


@dataclass(frozen=True)
class ReadBack:
    """What Riley read back before booking, and when: a booking needs the caller's answer to it."""

    callback_number: str
    window_id: str
    turn: int  # caller turns so far when it was read back; the caller's yes comes in a later one


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
    priority: bool = False  # set by the urgency gate; priority calls may book today's windows
    failed_attempts: dict[str, int] = field(default_factory=dict)  # field -> misses so far
    callback_reason: str | None = None
    # Booking. offered_windows: every window offered on this call, id -> how Riley says it
    # ("tomorrow, 8-10 am"); choose_window only accepts these ids. latest_offer: the ids in the
    # most recent offer, and offered_at_turn: caller turns so far when it was made (a choice
    # between two needs the caller to say which after it). held_window: the one the caller
    # picked. read_back: what Riley read back for the caller to confirm.
    offered_windows: dict[str, str] = field(default_factory=dict)
    latest_offer: list[str] = field(default_factory=list)
    offered_at_turn: int = 0
    held_window: str | None = None
    read_back: ReadBack | None = None
    booking_id: str | None = None
    outcome: Outcome | None = None
    # Conversation control, not business facts. `expecting`: the detail Riley just asked for, so
    # endpointing can be shortened for short answers (a name, a number, a ZIP). `acknowledged`:
    # whether this caller turn already got a spoken "Got it." (main.py resets it each turn);
    # `acks_said` rotates the wording, and `ack_line` is what this turn's was (None if it
    # couldn't be said). `caller_turns`: how many times the caller has spoken, set by tools.py
    # from the session history before each tool runs. `confirmed_aloud`: code said "You're all
    # set for ..." this turn, so the reply mustn't say it again (also reset each turn).
    expecting: str | None = None
    acknowledged: bool = False
    acks_said: int = 0
    ack_line: str | None = None
    caller_turns: int = 0
    confirmed_aloud: bool = False

    @property
    def closing(self) -> bool:
        """A gate or the safety script ended the call and code is hanging up. A booked call
        isn't closing: Riley still asks if there's anything else."""
        return self.outcome is not None and self.outcome is not Outcome.BOOKED
