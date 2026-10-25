"""Agent simulations: the final-state check (scenarios.py) and each simulated call's own world
(tools.start_simulation)."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from agent import scenarios, tools
from agent.scenarios import final_state_failure, scenario_now
from agent.state import CallState, Outcome

PHOENIX = ZoneInfo("America/Phoenix")


def booked(**fields) -> CallState:
    state = CallState(
        call_id="AJ_1",
        callback_number="6025550142",
        held_window="2026-10-22T10:00",
        booking_id="KC-1A2B3C4D",
        outcome=Outcome.BOOKED,
        category="ac_repair",
    )
    for name, value in fields.items():
        setattr(state, name, value)
    return state


def test_a_matching_final_state_passes():
    expected = {
        "outcome": "booked",
        "priority": False,
        "window": "2026-10-22T10:00",
        "callback_number": "6025550142",
        "category": "ac_repair",
    }
    assert final_state_failure(expected, booked()) is None


@pytest.mark.parametrize(
    ("expected", "problem"),
    [
        ({"outcome": "out_of_area"}, "outcome: expected 'out_of_area', got 'booked'"),
        ({"window": "2026-10-22T12:00"}, "window: expected '2026-10-22T12:00'"),
        ({"callback_number": "6025550184"}, "callback_number: expected '6025550184'"),
        ({"priority": True}, "priority: expected True, got False"),
    ],
)
def test_each_difference_is_named(expected, problem):
    assert problem in final_state_failure(expected, booked())


def test_a_call_no_gate_settled_counts_as_incomplete():
    # The session's close handler sets INCOMPLETE; the simulator may end the call first.
    state = CallState(call_id="AJ_1")
    assert final_state_failure({"outcome": "incomplete"}, state) is None


def test_a_window_only_counts_once_it_is_booked():
    held_not_booked = CallState(call_id="AJ_1", held_window="2026-10-22T10:00")
    assert "window: expected '2026-10-22T10:00', got None" in final_state_failure(
        {"window": "2026-10-22T10:00"}, held_not_booked
    )


def test_a_misspelled_key_fails_instead_of_checking_nothing():
    assert "unknown expected keys ['outcom']" in final_state_failure({"outcom": "x"}, booked())


def test_no_scenario_may_end_unbooked_with_a_booking_made():
    # Checked even when a scenario expects nothing (guardrail scenarios).
    state = booked(outcome=Outcome.CALLBACK_REQUESTED)
    assert "booking KC-1A2B3C4D made" in final_state_failure(None, state)


def test_the_clock_defaults_to_the_shared_moment_and_a_scenario_can_move_it():
    assert scenario_now({}, PHOENIX) == datetime(2026, 10, 21, 9, 30, tzinfo=PHOENIX)
    assert scenario_now({"now": "2026-10-24T15:00"}, PHOENIX) == datetime(
        2026, 10, 24, 15, 0, tzinfo=PHOENIX
    )
    assert scenarios.SIMULATION_NOW == "2026-10-21T09:30"


# --- tools.start_simulation: each simulated call sees its own calendar and clock ------------


@pytest.fixture
def job(monkeypatch):
    """Which job the code is running in, as get_job_context would say."""
    current = {"id": None}

    def get_job_context(*, required=True):
        return SimpleNamespace(job=SimpleNamespace(id=current["id"])) if current["id"] else None

    monkeypatch.setattr(tools, "get_job_context", get_job_context)
    yield current
    tools._simulated.clear()


def test_each_simulated_call_gets_its_own_calendar_and_clock(job, tmp_path):
    first = datetime(2026, 10, 21, 9, 30, tzinfo=PHOENIX)
    second = datetime(2026, 10, 24, 15, 0, tzinfo=PHOENIX)
    tools.start_simulation("AJ_1", tmp_path / "one", first)
    tools.start_simulation("AJ_2", tmp_path / "two", second)

    job["id"] = "AJ_1"
    one = tools.backends()
    assert tools.now() == first
    job["id"] = "AJ_2"
    assert tools.backends() is not one
    assert tools.now() == second


def test_real_calls_are_untouched_while_a_simulation_runs(job, tmp_path, monkeypatch):
    real = object()
    monkeypatch.setattr(tools, "_backends", real)
    tools.start_simulation("AJ_1", tmp_path, datetime(2026, 10, 21, 9, 30, tzinfo=PHOENIX))
    job["id"] = "AJ_9"  # a real call in the same process
    assert tools.backends() is real
    assert tools.now() != datetime(2026, 10, 21, 9, 30, tzinfo=PHOENIX)


def test_a_finished_simulation_is_forgotten(job, tmp_path, monkeypatch):
    real = object()
    monkeypatch.setattr(tools, "_backends", real)
    tools.start_simulation("AJ_1", tmp_path, datetime(2026, 10, 21, 9, 30, tzinfo=PHOENIX))
    tools.end_simulation("AJ_1")
    job["id"] = "AJ_1"
    assert tools.backends() is real
