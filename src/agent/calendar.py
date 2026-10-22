"""Mock appointment calendar: which windows are open, and booking one without double-booking.

Two halves:
- Pure window logic: every window in the next few days, how Riley says one ("tomorrow, 8-10 am"),
  and which to offer (earliest first, same-day only for priority calls, a day or time the caller
  asked for).
- `Calendar`: bookings in SQLite. Not a JSON file: LiveKit runs each call in its own process, and
  two calls taking the last place in a window at once would race on a file. SQLite's write lock
  makes "count, then insert" atomic across processes.

No LiveKit, no network. Appointments other customers already hold come from
config/mock_calendar.json, a weekly pattern, so the schedule isn't empty on a fresh start.
"""

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as clock_time
from pathlib import Path

from agent.config import REPO_ROOT, BookingRules

MOCK_CALENDAR_JSON = REPO_ROOT / "config" / "mock_calendar.json"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# By start hour, so "afternoon" finds the 12-2 and 2-4 windows and "evening" the 4-6 one.
PARTS_OF_DAY = {"morning": (0, 12), "afternoon": (12, 16), "evening": (16, 24)}


@dataclass(frozen=True)
class Window:
    start: datetime  # timezone-aware, business local time
    end: datetime

    @property
    def id(self) -> str:
        """ "2026-10-23T08:00": what the LLM passes back. Ids sort in time order."""
        return self.start.strftime("%Y-%m-%dT%H:%M")

    def when(self, today: date) -> str:
        """How Riley says it: "today, 2-4 pm", "tomorrow, 8-10 am", "Thursday, 10 am-12 pm".

        The horizon is under a week, so a weekday name is never ambiguous. spoken.py turns the
        times into words for TTS.
        """
        days_ahead = (self.start.date() - today).days
        if days_ahead == 0:
            day = "today"
        elif days_ahead == 1:
            day = "tomorrow"
        else:
            day = WEEKDAYS[self.start.weekday()].capitalize()
        return f"{day}, {_time_range(self.start, self.end)}"


def _clock(t: datetime) -> tuple[str, str]:
    hour = t.hour % 12 or 12
    return (str(hour) if t.minute == 0 else f"{hour}:{t.minute:02d}"), (
        "am" if t.hour < 12 else "pm"
    )


def _time_range(start: datetime, end: datetime) -> str:
    """ "8-10 am", "10 am-12 pm", "12-2 pm": am/pm once when both ends share it."""
    (s, s_period), (e, e_period) = _clock(start), _clock(end)
    return f"{s}-{e} {e_period}" if s_period == e_period else f"{s} {s_period}-{e} {e_period}"


def all_windows(rules: BookingRules, now: datetime) -> list[Window]:
    """Every window from today to the horizon on booking days, earliest first, booked or not."""
    windows = []
    for offset in range(rules.horizon_days + 1):
        day = now.date() + timedelta(days=offset)
        if WEEKDAYS[day.weekday()] not in rules.days:
            continue
        for start, end in rules.windows:
            windows.append(Window(_at(day, start, now), _at(day, end, now)))
    return windows


def _at(day: date, hhmm: str, now: datetime) -> datetime:
    return datetime.combine(day, clock_time.fromisoformat(hhmm), tzinfo=now.tzinfo)


def window_by_id(window_id: str, rules: BookingRules, now: datetime) -> Window | None:
    """The window with this id, if it's a real window within the horizon."""
    return next((w for w in all_windows(rules, now) if w.id == window_id), None)


def bookable(window: Window, rules: BookingRules, now: datetime, priority: bool) -> bool:
    """The timing rules (room left is the Calendar's job): nothing in the past, and today's
    windows only for priority calls, with time for a technician to get there."""
    if window.start.date() == now.date():
        if rules.same_day_for_priority_only and not priority:
            return False
        return window.start >= now + timedelta(minutes=rules.same_day_lead_minutes)
    return window.start > now


def pick_windows(
    open_windows: Sequence[Window],
    rules: BookingRules,
    now: datetime,
    *,
    priority: bool,
    day: str | None = None,
    part_of_day: str | None = None,
    after_id: str | None = None,
) -> list[Window]:
    """The windows to offer: bookable, earliest first, at most rules.max_offered.

    day: "today", "tomorrow" or a weekday name. part_of_day: a PARTS_OF_DAY key. after_id: only
    windows after this one (the caller asked for something later than what was offered).

    Priority calls see today's windows, so they're offered the earliest today if one is open,
    otherwise the earliest after that (business.md).
    """
    found = []
    for w in open_windows:
        if not bookable(w, rules, now, priority):
            continue
        if day is not None and not _on_day(w, day, now.date()):
            continue
        if part_of_day is not None:
            first, last = PARTS_OF_DAY[part_of_day]
            if not first <= w.start.hour < last:
                continue
        if after_id is not None and w.id <= after_id:
            continue
        found.append(w)
    return found[: rules.max_offered]


def _on_day(window: Window, day: str, today: date) -> bool:
    if day == "today":
        return window.start.date() == today
    if day == "tomorrow":
        return window.start.date() == today + timedelta(days=1)
    return WEEKDAYS[window.start.weekday()] == day


def booking_key(call_id: str, window_id: str) -> str:
    """Idempotency key for this call booking this window, also used for its CRM lead. A retried
    tool call produces the same key, so it finds the first booking instead of making a second."""
    return hashlib.sha256(f"{call_id}:{window_id}".encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Booking:
    booking_id: str
    window_id: str
    created: bool  # False: this key was already booked, and this is that booking


class WindowUnavailable(Exception):
    """The window is full, or can't be booked any more (too soon, or in the past)."""


def load_existing(path: Path = MOCK_CALENDAR_JSON) -> dict[str, dict[str, int]]:
    """Appointments other customers hold: weekday -> window start -> count."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {day: dict(starts) for day, starts in raw["existing_appointments"].items()}


class Calendar:
    """Bookings in SQLite, on top of the weekly pattern of other customers' appointments.

    Each method opens its own connection, so one Calendar can be used from worker threads
    (tools.py runs these calls off the event loop) and from several processes at once.
    delay_seconds is a demo switch that makes every call slow, to show Riley's filler line.
    """

    def __init__(
        self,
        path: Path,
        rules: BookingRules,
        existing: Mapping[str, Mapping[str, int]],
        delay_seconds: float = 0.0,
    ) -> None:
        self._path = path
        self._rules = rules
        self._existing = existing
        self._delay = delay_seconds
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS bookings (
                    idempotency_key TEXT PRIMARY KEY,
                    booking_id TEXT NOT NULL,
                    call_id TEXT NOT NULL,
                    window_id TEXT NOT NULL,
                    details TEXT NOT NULL,  -- JSON; fake test callers only
                    created_at TEXT NOT NULL
                )"""
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # isolation_level=None: no implicit transactions; book() starts its own. timeout: wait
        # up to 5 s for another process's write lock instead of failing at once.
        db = sqlite3.connect(self._path, timeout=5.0, isolation_level=None)
        try:
            yield db
        finally:
            db.close()

    def _already_held(self, window: Window) -> int:
        weekday = WEEKDAYS[window.start.weekday()]
        return self._existing.get(weekday, {}).get(window.start.strftime("%H:%M"), 0)

    def open_windows(self, now: datetime) -> list[Window]:
        """Windows in the horizon with room left, earliest first. Timing rules aren't applied
        here; pick_windows and book() apply them."""
        time.sleep(self._delay)
        with self._connect() as db:
            booked = dict(db.execute("SELECT window_id, COUNT(*) FROM bookings GROUP BY window_id"))
        return [
            w
            for w in all_windows(self._rules, now)
            if self._already_held(w) + booked.get(w.id, 0) < self._rules.per_window
        ]

    def book(
        self,
        *,
        key: str,
        call_id: str,
        window_id: str,
        details: Mapping[str, object],
        now: datetime,
        priority: bool,
    ) -> Booking:
        """Book a window, at most once per key. Raises WindowUnavailable if it can't be booked."""
        time.sleep(self._delay)
        with self._connect() as db:
            # BEGIN IMMEDIATE takes the write lock now, so no other call can book between our
            # count and our insert.
            db.execute("BEGIN IMMEDIATE")
            try:
                booking = self._book_locked(db, key, call_id, window_id, details, now, priority)
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")
        return booking

    def _book_locked(
        self,
        db: sqlite3.Connection,
        key: str,
        call_id: str,
        window_id: str,
        details: Mapping[str, object],
        now: datetime,
        priority: bool,
    ) -> Booking:
        row = db.execute(
            "SELECT booking_id, window_id FROM bookings WHERE idempotency_key = ?", (key,)
        ).fetchone()
        if row is not None:
            # Checked before anything else: a retry must find its booking even if the window
            # has filled up since.
            return Booking(booking_id=row[0], window_id=row[1], created=False)
        window = window_by_id(window_id, self._rules, now)
        if window is None or not bookable(window, self._rules, now, priority):
            raise WindowUnavailable(window_id)
        (booked,) = db.execute(
            "SELECT COUNT(*) FROM bookings WHERE window_id = ?", (window_id,)
        ).fetchone()
        if self._already_held(window) + booked >= self._rules.per_window:
            raise WindowUnavailable(window_id)
        booking_id = "KC-" + key[:8].upper()
        db.execute(
            "INSERT INTO bookings VALUES (?, ?, ?, ?, ?, ?)",
            (key, booking_id, call_id, window_id, json.dumps(details), now.isoformat()),
        )
        return Booking(booking_id=booking_id, window_id=window_id, created=True)
