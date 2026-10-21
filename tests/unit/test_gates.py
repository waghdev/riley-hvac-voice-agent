"""Every business decision, table-driven, with no LLM and no LiveKit (CLAUDE.md section 6)."""

import pytest

from agent.config import load_config
from agent.gates import (
    Decision,
    callback_gate,
    failed_attempt_gate,
    readiness_gate,
    safety_gate,
    service_area_gate,
    service_offered_gate,
    terminal_outcome,
    urgency_gate,
)
from agent.state import CallState, Outcome

CFG = load_config()


def state(**facts) -> CallState:
    return CallState(call_id="test", **facts)


READY = {
    "first_name": "Jordan",
    "callback_number": "6025550142",
    "zip_code": "85016",
    "category": "ac_repair",
    "symptoms": "blowing warm air",
}


# --- safety_gate --------------------------------------------------------------------------


@pytest.mark.parametrize("signal", sorted(CFG.safety_signals))
def test_every_safety_signal_redirects(signal):
    result = safety_gate(state(safety_signals={signal}), CFG)
    assert result.decision is Decision.SAFETY_REDIRECT
    assert signal in result.reason
    assert CFG.safety_script in result.say  # the exact script, word for word
    assert result.next_step == "say_exact_then_end_call"


def test_no_signal_is_clear():
    assert safety_gate(state(), CFG).decision is Decision.CLEAR


def test_unknown_signal_ids_are_ignored():
    # Tools only accept known ids; the gate doesn't act on anything else either.
    assert safety_gate(state(safety_signals={"spider"}), CFG).decision is Decision.CLEAR


# --- service_area_gate ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("zip_code", "decision", "next_step"),
    [
        ("85016", Decision.IN_AREA, "continue"),
        ("85003", Decision.IN_AREA, "continue"),
        ("85301", Decision.OUT_OF_AREA, "end_call"),  # Glendale: not served
        ("10001", Decision.OUT_OF_AREA, "end_call"),
        (None, Decision.INVALID_ZIP, "ask:zip_code"),  # the tool couldn't read a ZIP
    ],
)
def test_service_area(zip_code, decision, next_step):
    result = service_area_gate(state(zip_code=zip_code), CFG)
    assert result.decision is decision
    assert result.next_step == next_step


def test_out_of_area_says_where_we_serve_and_refers_nobody():
    result = service_area_gate(state(zip_code="85301"), CFG)
    assert CFG.service_area in result.say
    assert "85301" in result.reason


# --- service_offered_gate --------------------------------------------------------------------


@pytest.mark.parametrize("category", sorted(CFG.offered))
def test_offered_categories(category):
    assert service_offered_gate(state(category=category), CFG).decision is Decision.OFFERED


@pytest.mark.parametrize("category", sorted(CFG.not_offered))
def test_not_offered_categories_decline_and_close(category):
    result = service_offered_gate(state(category=category), CFG)
    assert result.decision is Decision.NOT_OFFERED
    assert result.next_step == "end_call"


# --- urgency_gate ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("facts", "decision"),
    [
        # No cooling plus a vulnerable occupant or a hot house: priority.
        ({"category": "ac_repair", "not_working": True, "vulnerable_occupant": "age_65_plus"},
         Decision.PRIORITY),
        ({"category": "heat_pump_repair", "not_working": True, "vulnerable_occupant": "infant"},
         Decision.PRIORITY),
        ({"category": "ac_repair", "not_working": True, "indoor_temp_f": 90}, Decision.PRIORITY),
        ({"category": "ac_repair", "not_working": True, "indoor_temp_f": 89}, Decision.STANDARD),
        # Cooling still works (noisy, leaking): standard, even with a vulnerable occupant.
        ({"category": "ac_repair", "not_working": False, "vulnerable_occupant": "infant"},
         Decision.STANDARD),
        # No heat: priority only with a vulnerable occupant; temperature doesn't count.
        ({"category": "heating_repair", "not_working": True,
          "vulnerable_occupant": "heat_affected_medical_condition"}, Decision.PRIORITY),
        ({"category": "heating_repair", "not_working": True, "indoor_temp_f": 95},
         Decision.STANDARD),
        # Other categories are never priority.
        ({"category": "maintenance", "not_working": True, "vulnerable_occupant": "infant"},
         Decision.STANDARD),
        ({"category": "thermostat", "not_working": True, "indoor_temp_f": 100},
         Decision.STANDARD),
        # A vulnerable-occupant value we don't recognise doesn't make it priority.
        ({"category": "ac_repair", "not_working": True, "vulnerable_occupant": "teenager"},
         Decision.STANDARD),
    ],
)  # fmt: skip
def test_urgency(facts, decision):
    assert urgency_gate(state(**facts), CFG).decision is decision


# --- readiness_gate --------------------------------------------------------------------------


def test_all_details_in_area_and_offered_is_ready():
    result = readiness_gate(state(**READY), CFG)
    assert result.decision is Decision.READY_TO_BOOK


@pytest.mark.parametrize("missing", ["first_name", "callback_number", "zip_code", "symptoms"])
def test_each_missing_field_is_named_and_asked_for(missing):
    result = readiness_gate(state(**{**READY, missing: None}), CFG)
    assert result.decision is Decision.MISSING
    assert missing in result.reason
    assert result.next_step == f"ask:{missing}"


def test_missing_fields_are_asked_in_order():
    result = readiness_gate(state(category="ac_repair"), CFG)
    assert result.reason == "missing:first_name,callback_number,zip_code,symptoms"
    assert result.next_step == "ask:first_name"


def test_blank_name_or_symptoms_count_as_missing():
    result = readiness_gate(state(**{**READY, "first_name": "  ", "symptoms": ""}), CFG)
    assert result.reason == "missing:first_name,symptoms"


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"zip_code": "85301"}, "out_of_area"),
        ({"category": "duct_cleaning"}, "not_offered"),
        ({"safety_signals": {"gas_smell"}}, "safety_signal"),
        # Conflicting signals (CLAUDE.md section 6): "no AC and I smell gas" -> safety wins.
        ({"not_working": True, "safety_signals": {"gas_smell"}}, "safety_signal"),
    ],
)
def test_ineligible_callers_can_never_be_booked(override, reason):
    result = readiness_gate(state(**{**READY, **override}), CFG)
    assert result.decision is Decision.NOT_BOOKABLE
    assert result.reason.startswith(reason)


def test_safety_beats_missing_fields():
    result = readiness_gate(state(safety_signals={"smoke"}), CFG)
    assert result.decision is Decision.NOT_BOOKABLE
    assert result.next_step == "say_exact_then_end_call"


# --- failed_attempt_gate (two strikes -> callback) ---------------------------------------


def test_first_miss_asks_again():
    result = failed_attempt_gate(state(failed_attempts={"zip_code": 1}), "zip_code", CFG)
    assert result.decision is Decision.ASK_AGAIN
    assert result.next_step == "ask:zip_code"


def test_second_miss_offers_a_callback_instead_of_looping():
    s = state(callback_number="6025550142", failed_attempts={"zip_code": 2})
    result = failed_attempt_gate(s, "zip_code", CFG)
    assert result.decision is Decision.OFFER_CALLBACK
    assert result.next_step == "take_callback_details"


def test_second_miss_on_the_number_itself_ends_politely():
    # No usable number means no callback; invite them to call back instead of looping.
    result = failed_attempt_gate(
        state(failed_attempts={"callback_number": 2}), "callback_number", CFG
    )
    assert result.decision is Decision.OFFER_CALLBACK
    assert result.next_step == "end_call"


# --- callback_gate -------------------------------------------------------------------------


def test_callback_needs_name_and_number():
    result = callback_gate(state(callback_reason="billing"), CFG)
    assert result.decision is Decision.MISSING
    assert result.next_step == "ask:first_name"


def test_callback_with_details_promises_the_callback_and_closes():
    s = state(first_name="Jordan", callback_number="6025550142", callback_reason="billing")
    result = callback_gate(s, CFG)
    assert result.decision is Decision.CALLBACK_READY
    assert CFG.callback_promise in result.say
    assert result.next_step == "end_call"


# --- terminal outcomes -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("decision", "outcome"),
    [
        (Decision.SAFETY_REDIRECT, Outcome.SAFETY_REDIRECT),
        (Decision.OUT_OF_AREA, Outcome.OUT_OF_AREA),
        (Decision.NOT_OFFERED, Outcome.NOT_OFFERED),
        (Decision.CALLBACK_READY, Outcome.CALLBACK_REQUESTED),
        (Decision.IN_AREA, None),
        (Decision.MISSING, None),
    ],
)
def test_terminal_outcomes(decision, outcome):
    assert terminal_outcome(decision) == outcome
