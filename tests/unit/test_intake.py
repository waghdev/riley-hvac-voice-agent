"""Tool logic end to end, without LiveKit: what each tool does to CallState and what it returns.

Mirrors the scenarios in CLAUDE.md section 9 at the decision-layer level.
"""

import pytest

from agent.config import load_config
from agent.gates import Decision
from agent.intake import (
    record_caller_details,
    record_issue,
    record_service_location,
    report_safety_hazard,
    request_callback,
)
from agent.state import CallState, Outcome

CFG = load_config()


@pytest.fixture
def s():
    return CallState(call_id="test")


def test_happy_path_collects_normalized_details_until_ready(s):
    r = record_issue(s, CFG, category="ac_repair", symptoms="blowing warm air", not_working=True)
    assert (r.decision, r.next_step) == (Decision.MISSING, "ask:first_name")

    r = record_caller_details(
        s, CFG, first_name=" Jordan ", callback_number="six oh two, five five five, oh one four two"
    )
    assert (r.decision, r.next_step) == (Decision.MISSING, "ask:zip_code")
    assert (s.first_name, s.callback_number) == ("Jordan", "6025550142")

    r = record_service_location(s, CFG, zip_code="eight five oh one six")
    assert r.decision is Decision.READY_TO_BOOK
    assert s.zip_code == "85016"
    assert s.outcome is None  # not decided until booking (M3)


def test_details_can_arrive_in_any_order(s):
    record_service_location(s, CFG, zip_code="85016")
    record_caller_details(s, CFG, callback_number="602-555-0142")
    r = record_issue(s, CFG, category="thermostat", symptoms="screen is blank")
    assert r.next_step == "ask:first_name"


def test_a_number_the_caller_never_said_is_asked_for_again(s):
    # Audio simulation, 2026-10-25: three pieces, eight digits, recorded as 602-501-4200 and
    # booked. Now it's a miss: Riley asks again, and gives up after two (failed_attempt_gate).
    said = ["Six zero two.", "Five.", "O. One four two."]
    r = record_caller_details(s, CFG, callback_number="602-501-4200", caller_said=said)
    assert (r.decision, r.next_step) == (Decision.ASK_AGAIN, "ask:callback_number")
    assert s.callback_number is None
    said.append("six oh two, five five five, oh one four two")
    record_caller_details(s, CFG, callback_number="602-555-0142", caller_said=said)
    assert s.callback_number == "6025550142"


def test_a_zip_the_caller_never_said_is_asked_for_again(s):
    r = record_service_location(s, CFG, zip_code="85016", caller_said=["eight five oh one"])
    assert (r.decision, r.next_step) == (Decision.ASK_AGAIN, "ask:zip_code")
    assert s.zip_code is None


def test_a_callback_request_checks_the_number_too(s):
    r = request_callback(
        s, CFG, reason="billing", first_name="Jordan", callback_number="602-555-0100",
        caller_said=["it's Jordan, six oh two five five five"],
    )  # fmt: skip
    assert r.next_step == "ask:callback_number" and s.callback_number is None


def test_out_of_area_zip_ends_the_call_with_that_outcome(s):
    r = record_service_location(s, CFG, zip_code="85301")
    assert r.decision is Decision.OUT_OF_AREA
    assert r.next_step == "end_call"
    assert s.outcome is Outcome.OUT_OF_AREA


def test_unreadable_zip_asks_again_then_offers_a_callback(s):
    record_caller_details(s, CFG, first_name="Jordan", callback_number="6025550142")
    first = record_service_location(s, CFG, zip_code="somewhere near the park")
    assert (first.decision, first.next_step) == (Decision.ASK_AGAIN, "ask:zip_code")
    second = record_service_location(s, CFG, zip_code="I don't know")
    assert (second.decision, second.next_step) == (Decision.OFFER_CALLBACK, "take_callback_details")


def test_a_good_value_resets_the_miss_count(s):
    record_service_location(s, CFG, zip_code="no idea")
    record_service_location(s, CFG, zip_code="85016")
    assert "zip_code" not in s.failed_attempts


def test_unreadable_number_twice_ends_politely_as_incomplete(s):
    record_caller_details(s, CFG, callback_number="five five five")
    r = record_caller_details(s, CFG, callback_number="call me whenever")
    assert (r.decision, r.next_step) == (Decision.OFFER_CALLBACK, "end_call")
    assert s.outcome is Outcome.INCOMPLETE


def test_service_not_offered_declines_with_that_outcome(s):
    r = record_issue(s, CFG, category="commercial_or_rooftop", symptoms="rooftop unit at my store")
    assert r.decision is Decision.NOT_OFFERED
    assert s.outcome is Outcome.NOT_OFFERED


def test_unknown_category_is_rejected_so_the_llm_can_correct_it(s):
    with pytest.raises(ValueError, match="unknown category"):
        record_issue(s, CFG, category="pool_heater", symptoms="cold pool")


def test_gas_smell_mid_call_after_a_zip_overrides_everything(s):
    record_issue(s, CFG, category="ac_repair", symptoms="not cooling", not_working=True)
    record_service_location(s, CFG, zip_code="85016")
    r = report_safety_hazard(s, CFG, signal="gas_smell")
    assert r.decision is Decision.SAFETY_REDIRECT
    assert CFG.safety_script in r.say
    assert s.outcome is Outcome.SAFETY_REDIRECT
    # And nothing afterwards can make the call bookable.
    after = record_caller_details(s, CFG, first_name="Jordan", callback_number="6025550142")
    assert after.decision is Decision.NOT_BOOKABLE


def test_no_ac_and_i_smell_gas_in_one_breath_is_a_safety_redirect(s):
    r = record_issue(
        s,
        CFG,
        category="ac_repair",
        symptoms="no AC",
        not_working=True,
        safety_signals=["gas_smell"],
    )
    assert r.decision is Decision.SAFETY_REDIRECT


def test_unknown_hazard_id_is_rejected(s):
    with pytest.raises(ValueError, match="unknown safety signal"):
        report_safety_hazard(s, CFG, signal="weird_noise")


CALLER = ["hi, my AC died and my eighty-year-old mom is here with me"]


def test_priority_is_recorded_and_mentioned(s):
    r = record_issue(
        s,
        CFG,
        category="ac_repair",
        symptoms="no cooling at all",
        not_working=True,
        vulnerable_occupant="age_65_plus",
        vulnerable_occupant_words="My eighty-year-old mom is here",
        caller_said=CALLER,
    )
    assert s.priority is True
    assert "priority" in r.say
    assert r.next_step == "ask:first_name"


def test_unrecognised_vulnerable_occupant_is_ignored(s):
    record_issue(
        s, CFG, category="ac_repair", symptoms="x", not_working=True, vulnerable_occupant="cat",
        vulnerable_occupant_words="my eighty-year-old mom", caller_said=CALLER,
    )  # fmt: skip
    assert s.vulnerable_occupant is None and s.priority is False


@pytest.mark.parametrize(
    ("words", "caller_said"),
    [
        # Bug (debugger call, 2026-10-22): "infant" for a caller who never mentioned anyone.
        (None, ["hi, my AC stopped cooling, it's blowing warm air"]),
        ("there's a baby at home", ["hi, my AC stopped cooling, it's blowing warm air"]),
        ("baby", ["my AC is broken"]),  # words the caller didn't say
        ("ba", ["ba ba ba"]),  # too short to be evidence
    ],
)
def test_a_vulnerable_occupant_needs_the_callers_own_words(s, words, caller_said):
    record_issue(
        s, CFG, category="ac_repair", symptoms="warm air", not_working=True,
        vulnerable_occupant="infant", vulnerable_occupant_words=words, caller_said=caller_said,
    )  # fmt: skip
    assert s.vulnerable_occupant is None and s.priority is False


def test_callback_request_collects_name_and_number_then_promises(s):
    r = request_callback(s, CFG, reason="billing")
    assert r.next_step == "ask:first_name"
    r = record_caller_details(s, CFG, first_name="Jordan", callback_number="602 555 0142")
    assert r.decision is Decision.CALLBACK_READY
    assert s.outcome is Outcome.CALLBACK_REQUESTED


def test_callback_with_details_in_one_go(s):
    r = request_callback(
        s, CFG, reason="wants_human", first_name="Jordan", callback_number="6025550142"
    )
    assert r.decision is Decision.CALLBACK_READY


def test_unknown_callback_reason_becomes_other(s):
    request_callback(s, CFG, reason="weather chat")
    assert s.callback_reason == "other"


def test_a_corrected_number_replaces_the_old_one(s):
    record_caller_details(s, CFG, callback_number="602-555-0142")
    record_caller_details(s, CFG, callback_number="602-555-0199")
    assert s.callback_number == "6025550199"


def test_next_field_is_remembered_for_endpointing(s):
    record_issue(s, CFG, category="ac_repair", symptoms="warm air")
    assert s.expecting == "first_name"
    record_caller_details(s, CFG, first_name="Jordan", callback_number="6025550142")
    assert s.expecting == "zip_code"
    record_service_location(s, CFG, zip_code="85016")
    assert s.expecting is None


@pytest.mark.parametrize("placeholder", ["unknown", "Unknown", "N/A", "none", "not provided", " "])
def test_placeholder_values_from_the_llm_count_as_not_given(s, placeholder):
    # Bug (debugger call, 2026-10-21): for "can I talk to a real person about my bill?" the LLM
    # called request_callback(first_name="unknown", callback_number="unknown"). The name was
    # stored as "unknown" and the fake number counted as a failed attempt.
    r = request_callback(
        s, CFG, reason="billing", first_name=placeholder, callback_number=placeholder
    )
    assert s.first_name is None
    assert s.callback_number is None
    assert s.failed_attempts == {}
    assert r.next_step == "ask:first_name"


@pytest.mark.parametrize(
    ("said", "stored"), [(0, None), (-1, None), (500, None), (93, 93), (72, 72)]
)
def test_implausible_indoor_temperatures_are_not_stored(s, said, stored):
    # Bug (audio debugger call, 2026-10-21): the LLM passed indoor_temp_f=0 for "not mentioned".
    record_issue(s, CFG, category="ac_repair", symptoms="warm air", indoor_temp_f=said)
    assert s.indoor_temp_f == stored
