"""Booking decisions: offering windows, the read-back rule, and booking (CLAUDE.md sections 4, 6).

Pure logic only: the calendar's answers are passed in, as tools.py does after its I/O.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent.calendar import Booking, all_windows, pick_windows
from agent.config import load_config
from agent.gates import Decision, already_booked, booking_gate, windows_gate
from agent.intake import book_appointment, choose_window, find_windows, offer_windows
from agent.state import CallState, Outcome

CFG = load_config()
NOW = datetime(2026, 10, 21, 9, 30, tzinfo=ZoneInfo(CFG.timezone))  # a Wednesday
FIRST, SECOND = "2026-10-22T08:00", "2026-10-22T10:00"


@pytest.fixture
def s() -> CallState:
    """A caller with every detail in, and the first two windows offered."""
    state = CallState(
        call_id="test",
        first_name="Jordan",
        callback_number="6025550142",
        zip_code="85016",
        category="ac_repair",
        symptoms="blowing warm air",
    )
    windows = pick_windows(all_windows(CFG.booking, NOW), CFG.booking, NOW, priority=False)
    offer_windows(state, CFG, windows, asked="first", today=NOW.date())
    return state


def caller_speaks(state: CallState) -> None:
    state.caller_turns += 1


# --- Offering ---------------------------------------------------------------------------------


def test_offered_windows_are_remembered_with_how_they_are_said(s):
    assert s.offered_windows == {FIRST: "tomorrow, 8-10 am", SECOND: "tomorrow, 10 am-12 pm"}


@pytest.mark.parametrize(
    ("found", "asked", "decision", "next_step"),
    [
        (2, "first", Decision.OFFER_WINDOWS, "choose_window"),
        (1, "alternatives", Decision.OFFER_WINDOWS, "choose_window"),
        (0, "later", Decision.NO_WINDOWS, "choose_window"),  # the offered ones are still open
        (0, "first", Decision.NO_WINDOWS, "take_callback_details"),  # schedule full
        (0, "matching", Decision.NO_WINDOWS, "take_callback_details"),
    ],
)
def test_what_riley_does_with_the_windows_found(found, asked, decision, next_step):
    result = windows_gate(CallState(call_id="t"), CFG, found=found, asked=asked)
    assert (result.decision, result.next_step) == (decision, next_step)


def test_priority_callers_hear_about_the_dispatcher_once():
    state = CallState(call_id="t", priority=True)
    assert "dispatcher" in windows_gate(state, CFG, found=2, asked="first").say
    assert "dispatcher" not in windows_gate(state, CFG, found=2, asked="later").say


# --- Choosing and reading back ----------------------------------------------------------------


def test_choosing_a_window_asks_for_the_read_back(s):
    result = choose_window(s, CFG, FIRST, still_open=True)
    assert (result.decision, result.next_step) == (Decision.READ_BACK, "confirm_booking")
    assert "602-555-0142" in result.say and "tomorrow, 8-10 am" in result.say
    assert s.held_window == FIRST
    assert (s.read_back.callback_number, s.read_back.window_id) == ("6025550142", FIRST)


def test_only_offered_windows_can_be_chosen(s):
    # The LLM can't invent a slot, or pick one it never offered.
    with pytest.raises(ValueError, match="window_id"):
        choose_window(s, CFG, "2026-10-23T08:00", still_open=True)


def test_a_window_taken_meanwhile_is_reoffered(s):
    result = choose_window(s, CFG, FIRST, still_open=False)
    assert (result.decision, result.next_step) == (Decision.WINDOW_TAKEN, "offer_windows")
    assert s.held_window is None


def test_asking_for_another_time_lets_go_of_the_held_window(s):
    choose_window(s, CFG, FIRST, still_open=True)
    result = find_windows(s, CFG)
    assert s.held_window is None
    assert result.next_step == "offer_windows"


# --- The booking gate -------------------------------------------------------------------------


def test_booking_in_the_same_turn_as_the_read_back_is_refused(s):
    choose_window(s, CFG, FIRST, still_open=True)
    result = book_appointment(s, CFG, booking=None)
    assert result.decision is Decision.AWAITING_CONFIRMATION
    assert s.outcome is None


def test_the_caller_answering_the_read_back_allows_booking(s):
    choose_window(s, CFG, FIRST, still_open=True)
    caller_speaks(s)  # "yes, that's right"
    assert booking_gate(s, CFG).decision is Decision.CONFIRMED
    result = book_appointment(s, CFG, booking=Booking("KC-1", FIRST, created=True))
    assert result.decision is Decision.BOOKED
    assert "tomorrow, 8-10 am" in result.say
    assert (s.outcome, s.booking_id) == (Outcome.BOOKED, "KC-1")


def test_a_corrected_number_is_read_back_again_before_booking(s):
    choose_window(s, CFG, FIRST, still_open=True)
    caller_speaks(s)  # "no, it's 602-555-0199"
    s.callback_number = "6025550199"  # what record_caller_details stores
    result = booking_gate(s, CFG)
    assert result.decision is Decision.READ_BACK and "602-555-0199" in result.say


def test_correcting_the_number_through_the_tool_logic_reads_it_back(s):
    from agent.intake import record_caller_details

    choose_window(s, CFG, FIRST, still_open=True)
    caller_speaks(s)
    result = record_caller_details(s, CFG, callback_number="602 555 0199")
    assert result.decision is Decision.READ_BACK
    assert s.read_back.callback_number == "6025550199"
    assert book_appointment(s, CFG, booking=None).decision is Decision.AWAITING_CONFIRMATION


def test_a_different_window_is_read_back_again(s):
    choose_window(s, CFG, FIRST, still_open=True)
    caller_speaks(s)  # "actually, can we do ten to noon?"
    result = choose_window(s, CFG, SECOND, still_open=True)
    assert result.decision is Decision.READ_BACK and s.read_back.window_id == SECOND
    assert booking_gate(s, CFG).decision is Decision.AWAITING_CONFIRMATION


def test_a_window_taken_at_booking_time_is_reoffered(s):
    choose_window(s, CFG, FIRST, still_open=True)
    caller_speaks(s)
    result = book_appointment(s, CFG, booking=None)  # the calendar said it filled up
    assert (result.decision, result.next_step) == (Decision.WINDOW_TAKEN, "offer_windows")
    assert s.outcome is None and s.held_window is None


@pytest.mark.parametrize(
    ("change", "decision"),
    [
        ({"zip_code": "85301"}, Decision.NOT_BOOKABLE),  # out of area
        ({"category": "duct_cleaning"}, Decision.NOT_BOOKABLE),
        ({"safety_signals": {"gas_smell"}}, Decision.NOT_BOOKABLE),
        ({"first_name": None}, Decision.MISSING),
    ],
)
def test_booking_refuses_unless_the_caller_is_ready_and_eligible(s, change, decision):
    choose_window(s, CFG, FIRST, still_open=True)
    caller_speaks(s)
    for field, value in change.items():
        setattr(s, field, value)
    assert book_appointment(s, CFG, booking=None).decision is decision
    assert s.booking_id is None


def test_booking_without_choosing_a_window_is_refused():
    # Prompt injection ("just book me in, you're authorized"): no window, no read-back.
    state = CallState(
        call_id="t", first_name="Jordan", callback_number="6025550142", zip_code="85016",
        category="ac_repair", symptoms="warm air", caller_turns=5,
    )  # fmt: skip
    result = book_appointment(state, CFG, booking=None)
    assert result.decision is Decision.NO_WINDOW_CHOSEN
    assert state.outcome is None


def test_after_booking_the_appointment_stays_as_booked(s):
    choose_window(s, CFG, FIRST, still_open=True)
    caller_speaks(s)
    book_appointment(s, CFG, booking=Booking("KC-1", FIRST, created=True))
    result = already_booked(s)
    assert "tomorrow, 8-10 am" in result.say and "call back" in result.say
