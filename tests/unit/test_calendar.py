"""The mock calendar: which windows exist, which are offered, and booking without double-booking.

A fixed clock: Wednesday 2026-10-21, 9:30 am in Phoenix. No LiveKit, no network; SQLite files
live in pytest's tmp_path.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent.calendar import (
    Calendar,
    WindowUnavailable,
    all_windows,
    booking_key,
    load_existing,
    pick_windows,
    window_by_id,
)
from agent.config import load_config

CFG = load_config()
RULES = CFG.booking
PHX = ZoneInfo(CFG.timezone)
NOW = datetime(2026, 10, 21, 9, 30, tzinfo=PHX)  # a Wednesday
TODAY = NOW.date()


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=PHX)


def ids(windows) -> list[str]:
    return [w.id for w in windows]


@pytest.fixture
def empty(tmp_path) -> Calendar:
    """No other customers' appointments: every window has room for two."""
    return Calendar(tmp_path / "calendar.sqlite3", RULES, existing={})


def book(cal: Calendar, call_id: str, window_id: str, now=NOW, priority=False):
    return cal.book(
        key=booking_key(call_id, window_id),
        call_id=call_id,
        window_id=window_id,
        details={"first_name": "Jordan"},
        now=now,
        priority=priority,
    )


# --- Windows ----------------------------------------------------------------------------------


def test_windows_cover_six_days_ahead_without_sundays():
    windows = all_windows(RULES, NOW)
    days = sorted({w.start.day for w in windows})
    assert days == [21, 22, 23, 24, 26, 27]  # Wednesday to Tuesday; Sunday the 25th skipped
    assert len(windows) == 6 * 5
    assert ids(windows) == sorted(ids(windows))  # earliest first, and ids sort the same way


@pytest.mark.parametrize(
    ("start", "said"),
    [
        (at(21, 14), "today, 2-4 pm"),
        (at(22, 8), "tomorrow, 8-10 am"),
        (at(22, 10), "tomorrow, 10 am-12 pm"),
        (at(23, 12), "Friday, 12-2 pm"),
        (at(26, 16), "Monday, 4-6 pm"),
    ],
)
def test_how_riley_says_a_window(start, said):
    assert window_by_id(start.strftime("%Y-%m-%dT%H:%M"), RULES, NOW).when(TODAY) == said


def test_an_id_that_is_not_a_window_finds_nothing():
    assert window_by_id("2026-10-22T09:00", RULES, NOW) is None  # not a window start
    assert window_by_id("2026-10-25T08:00", RULES, NOW) is None  # Sunday
    assert window_by_id("2026-11-30T08:00", RULES, NOW) is None  # past the horizon
    assert window_by_id("tomorrow morning", RULES, NOW) is None


# --- What gets offered ------------------------------------------------------------------------


def test_standard_calls_are_offered_the_two_earliest_from_tomorrow():
    offered = pick_windows(all_windows(RULES, NOW), RULES, NOW, priority=False)
    assert ids(offered) == ["2026-10-22T08:00", "2026-10-22T10:00"]


def test_priority_calls_get_today_with_time_to_get_there():
    # 9:30 now: 8-10 has started and 10-12 is under 60 minutes away, so 12-2 is the earliest.
    offered = pick_windows(all_windows(RULES, NOW), RULES, NOW, priority=True)
    assert ids(offered) == ["2026-10-21T12:00", "2026-10-21T14:00"]


def test_priority_late_in_the_day_gets_tomorrows_earliest():
    late = at(21, 16, 30)
    offered = pick_windows(all_windows(RULES, late), RULES, late, priority=True)
    assert ids(offered) == ["2026-10-22T08:00", "2026-10-22T10:00"]


def test_saturday_evening_rolls_past_sunday_to_monday():
    saturday = at(24, 19)
    offered = pick_windows(all_windows(RULES, saturday), RULES, saturday, priority=False)
    assert ids(offered)[0] == "2026-10-26T08:00"


@pytest.mark.parametrize(
    ("day", "part", "expected"),
    [
        ("friday", "afternoon", ["2026-10-23T12:00", "2026-10-23T14:00"]),
        ("tomorrow", None, ["2026-10-22T08:00", "2026-10-22T10:00"]),
        (None, "evening", ["2026-10-22T16:00", "2026-10-23T16:00"]),
        ("saturday", "morning", ["2026-10-24T08:00", "2026-10-24T10:00"]),
        ("today", None, []),  # same-day windows are for priority calls only
    ],
)
def test_the_caller_can_ask_for_a_day_or_time(day, part, expected):
    offered = pick_windows(
        all_windows(RULES, NOW), RULES, NOW, priority=False, day=day, part_of_day=part
    )
    assert ids(offered) == expected


def test_asking_for_later_skips_what_was_offered():
    offered = pick_windows(
        all_windows(RULES, NOW), RULES, NOW, priority=False, after_id="2026-10-22T10:00"
    )
    assert ids(offered) == ["2026-10-22T12:00", "2026-10-22T14:00"]


# --- Room left, and booking -------------------------------------------------------------------


def test_the_weekly_pattern_fills_windows(tmp_path):
    cal = Calendar(tmp_path / "c.sqlite3", RULES, load_existing())
    offered = pick_windows(cal.open_windows(NOW), RULES, NOW, priority=False)
    # Thursday 8-10 is full in config/mock_calendar.json; 10-12 has one place left.
    assert ids(offered) == ["2026-10-22T10:00", "2026-10-22T12:00"]


def test_the_mock_calendar_file_is_valid():
    existing = load_existing()
    starts = {start for start, _ in RULES.windows}
    for day, counts in existing.items():
        assert day in RULES.days
        assert set(counts) <= starts
        assert all(0 <= n <= RULES.per_window for n in counts.values())


def test_booking_takes_a_place_and_a_full_window_closes(empty):
    window = "2026-10-22T08:00"
    book(empty, "call-a", window)
    assert window in ids(empty.open_windows(NOW))  # one place left
    book(empty, "call-b", window)
    assert window not in ids(empty.open_windows(NOW))
    with pytest.raises(WindowUnavailable):
        book(empty, "call-c", window)


def test_booking_twice_with_the_same_key_books_once(empty):
    # A retried tool call: same call, same window, so same key.
    first = book(empty, "call-a", "2026-10-22T08:00")
    again = book(empty, "call-a", "2026-10-22T08:00")
    assert first.created and not again.created
    assert again.booking_id == first.booking_id
    book(empty, "call-b", "2026-10-22T08:00")  # the second place is still free


def test_a_retry_finds_its_booking_even_after_the_window_fills(empty):
    first = book(empty, "call-a", "2026-10-22T08:00")
    book(empty, "call-b", "2026-10-22T08:00")
    assert book(empty, "call-a", "2026-10-22T08:00").booking_id == first.booking_id


@pytest.mark.parametrize(
    ("window", "priority"),
    [
        ("2026-10-21T08:00", True),  # already started
        ("2026-10-21T10:00", True),  # under 60 minutes away
        ("2026-10-21T14:00", False),  # today, and not a priority call
        ("2026-10-25T08:00", False),  # Sunday: not a window
    ],
)
def test_windows_the_timing_rules_exclude_cannot_be_booked(empty, window, priority):
    with pytest.raises(WindowUnavailable):
        book(empty, "call-a", window, priority=priority)


def test_two_processes_sharing_the_file_cannot_overbook(tmp_path):
    # Each call runs in its own process with its own Calendar on the same SQLite file.
    path = tmp_path / "shared.sqlite3"
    one, two = (Calendar(path, RULES, existing={}) for _ in range(2))
    book(one, "call-a", "2026-10-22T08:00")
    book(two, "call-b", "2026-10-22T08:00")
    with pytest.raises(WindowUnavailable):
        book(one, "call-c", "2026-10-22T08:00")


def test_booking_keys_are_stable_per_call_and_window():
    assert booking_key("call-a", "2026-10-22T08:00") == booking_key("call-a", "2026-10-22T08:00")
    assert booking_key("call-a", "2026-10-22T08:00") != booking_key("call-a", "2026-10-22T10:00")
    assert booking_key("call-a", "2026-10-22T08:00") != booking_key("call-b", "2026-10-22T08:00")
