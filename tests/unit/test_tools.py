"""tools.py behavior that doesn't need a live session, using a stand-in RunContext.

The calendar and outbox are real, in pytest's tmp_path; the clock is pinned to a Wednesday at
9:30 am in Phoenix; there's no CRM URL, so leads stay pending in the outbox.
"""

import time
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from livekit.agents.llm import ChatMessage

from agent import prompts, tools
from agent.calendar import Calendar
from agent.crm_client import PENDING, CrmClient, LeadSender, Outbox
from agent.state import CallState, Outcome

NOW = datetime(2026, 10, 21, 9, 30, tzinfo=ZoneInfo("America/Phoenix"))
FIRST = "2026-10-22T08:00"  # Thursday 8-10 am, the first window offered at NOW


class ClosingSession:
    """Like AgentSession once shutdown has started: say() refuses."""

    def __init__(self) -> None:
        self.options: list[dict] = []
        self.history = SimpleNamespace(items=[])

    def say(self, *args, **kwargs):
        raise RuntimeError("AgentSession is closing, cannot use say()")

    def update_options(self, **kwargs) -> None:
        self.options.append(kwargs)


class OpenSession:
    """A running session: records what's said, option changes, and the caller's turns."""

    def __init__(self) -> None:
        self.said: list[str] = []
        self.options: list[dict] = []
        self.history = SimpleNamespace(items=[])

    def say(self, line, **kwargs):
        self.said.append(line)
        return SimpleNamespace(add_done_callback=lambda cb: None)

    def update_options(self, **kwargs) -> None:
        self.options.append(kwargs)

    def caller_says(self, text: str) -> None:
        self.history.items.append(ChatMessage(role="user", content=[text]))


def context(session, **facts) -> SimpleNamespace:
    handle = SimpleNamespace(add_done_callback=lambda cb: None)  # the turn's speech handle
    return SimpleNamespace(
        userdata=CallState(call_id="t", **facts),
        session=session,
        speech_handle=handle,
        disallow_interruptions=lambda: None,
    )


READY = {
    "first_name": "Jordan",
    "callback_number": "6025550142",
    "category": "ac_repair",
    "symptoms": "blowing warm air",
}


def new_turn(ctx, said: str = "...") -> None:
    """What main.py does when the caller speaks: a fresh turn may get its own "Got it."."""
    ctx.userdata.acknowledged = False
    ctx.session.caller_says(said)


@pytest.fixture
def backends(tmp_path, monkeypatch) -> tools.Backends:
    b = tools.Backends(
        calendar=Calendar(tmp_path / "calendar.sqlite3", tools.CONFIG.booking, existing={}),
        leads=LeadSender(CrmClient(None, Outbox(tmp_path / "outbox.sqlite3"))),
    )
    monkeypatch.setattr(tools, "_backends", b)
    monkeypatch.setattr(tools, "now", lambda: NOW)
    return b


# --- Closing sessions and decided calls (M2 bugs) ---------------------------------------------


def test_acknowledging_while_the_session_closes_is_skipped_not_raised():
    # Bug (cloud call 1, 2026-10-22): a tool ran while the session was already closing, the
    # acknowledgement's say() raised, and the tool call failed with an exception.
    ctx = context(ClosingSession())
    tools._acknowledge(ctx)
    assert ctx.userdata.ack_line is None


async def test_a_tool_result_still_comes_back_while_the_session_closes():
    ctx = context(ClosingSession())
    out = await tools._run(ctx, tools.intake.record_service_location, zip_code="85016")
    assert out is not None and out["decision"] == "MISSING"


async def test_tools_are_ignored_once_the_call_is_decided():
    # Bug (cloud call, 2026-10-22): after an out-of-area ZIP ended the call, a stray "two."
    # reached the model, which re-recorded it as a ZIP while Riley was saying goodbye.
    ctx = context(OpenSession())
    await tools._run(ctx, tools.intake.record_service_location, zip_code="80139")  # out of area
    assert ctx.userdata.outcome is not None
    before = (ctx.userdata.zip_code, dict(ctx.userdata.failed_attempts))
    out = await tools._run(ctx, tools.intake.record_service_location, zip_code="two")
    assert out is None  # no reply, nothing recorded
    assert (ctx.userdata.zip_code, ctx.userdata.failed_attempts) == before


async def test_a_safety_report_still_plays_after_the_call_is_decided():
    session = OpenSession()
    ctx = context(session)
    await tools._run(ctx, tools.intake.record_service_location, zip_code="80139")
    await tools._run(ctx, tools.intake.report_safety_hazard, signal="gas_smell")
    assert tools.CONFIG.safety_script in session.said


def test_digit_answers_get_a_longer_minimum_wait():
    # Bug (same call): "Eight zero one three nine" then "two." 0.7 s later, split into two
    # turns because the detector was confident and committed after 0.3 s.
    state = CallState(call_id="t")
    for field in ("callback_number", "zip_code"):
        state.expecting = field
        assert tools.endpointing_for(state) == {"min_delay": 0.6, "max_delay": 1.0}
    state.expecting = "first_name"
    assert tools.endpointing_for(state) == {"min_delay": 0.3, "max_delay": 1.0}
    state.expecting = None
    assert tools.endpointing_for(state) == {"min_delay": 0.3, "max_delay": 2.5}


# --- Offering windows -------------------------------------------------------------------------


async def test_complete_details_come_back_with_windows_to_offer(backends):
    ctx = context(OpenSession(), **READY)
    out = await tools._run(ctx, tools.intake.record_service_location, zip_code="85016")
    assert out["next_step"] == "choose_window"
    assert out["windows"] == [
        {"id": "2026-10-22T08:00", "when": "tomorrow, 8-10 am"},
        {"id": "2026-10-22T10:00", "when": "tomorrow, 10 am-12 pm"},
    ]


async def test_a_slow_calendar_gets_the_filler_line_after_the_acknowledgement(
    backends, monkeypatch
):
    monkeypatch.setattr(tools, "FILLER_AFTER_SECONDS", 0.05)
    slow = backends.calendar.open_windows

    def slow_open_windows(now):
        time.sleep(0.3)
        return slow(now)

    monkeypatch.setattr(backends.calendar, "open_windows", slow_open_windows)
    session = OpenSession()
    ctx = context(session, **READY)
    await tools._run(ctx, tools.intake.record_service_location, zip_code="85016")
    assert session.said == ["Got it.", prompts.CHECKING_SCHEDULE]


async def test_a_fast_calendar_gets_no_filler(backends):
    session = OpenSession()
    await tools._run(
        context(session, **READY), tools.intake.record_service_location, zip_code="85016"
    )
    assert session.said == ["Got it."]


async def test_a_broken_calendar_offers_a_callback_instead(backends, monkeypatch):
    def broken(now):
        raise OSError("disk full")

    monkeypatch.setattr(backends.calendar, "open_windows", broken)
    ctx = context(OpenSession(), **READY)
    out = await tools._run(ctx, tools.intake.record_service_location, zip_code="85016")
    assert (out["decision"], out["next_step"]) == ("NO_WINDOWS", "take_callback_details")


# --- Booking through the real tools -----------------------------------------------------------


async def offered_and_chosen(ctx) -> dict:
    """The caller gives the ZIP (windows offered), then picks the first window."""
    ctx.session.caller_says("eight five oh one six")
    await tools.record_service_location(ctx, "85016")
    new_turn(ctx, "the first one works")
    return await tools.choose_window(ctx, FIRST)


async def test_choosing_a_window_asks_for_the_read_back(backends):
    ctx = context(OpenSession(), **READY)
    out = await offered_and_chosen(ctx)
    assert (out["decision"], out["next_step"]) == ("READ_BACK", "confirm_booking")
    assert "602-555-0142" in out["say"] and "tomorrow, 8-10 am" in out["say"]


async def test_a_bare_mhmm_doesnt_choose_a_window(backends):
    # Bug (audio simulation, 2026-10-27): "Mhmm." after two windows were offered, and the model
    # chose the first. The tool hears what the caller said since the offer, not the model.
    ctx = context(OpenSession(), **READY)
    ctx.session.caller_says("eight five oh one six")
    await tools.record_service_location(ctx, "85016")
    new_turn(ctx, "Mhmm.")
    out = await tools.choose_window(ctx, FIRST)
    assert (out["decision"], out["next_step"]) == ("NO_WINDOW_CHOSEN", "choose_window")
    assert ctx.userdata.held_window is None


async def test_booking_in_the_same_turn_as_the_read_back_is_refused(backends):
    ctx = context(OpenSession(), **READY)
    await offered_and_chosen(ctx)
    out = await tools.book_appointment(ctx)
    assert out["decision"] == "AWAITING_CONFIRMATION"
    assert ctx.userdata.outcome is None
    assert backends.leads.client.outbox.pending() == []  # no booking, so no lead


async def test_a_confirmed_booking_is_stored_and_its_lead_queued(backends):
    ctx = context(OpenSession(), **READY)
    await offered_and_chosen(ctx)
    new_turn(ctx)  # "yes, that's right"
    out = await tools.book_appointment(ctx)
    assert out["decision"] == "BOOKED"
    assert ctx.userdata.outcome is Outcome.BOOKED and ctx.userdata.booking_id
    await backends.leads.drain(timeout=5)
    ((key, lead),) = backends.leads.client.outbox.pending()  # no CRM URL: waits in the outbox
    assert (lead["kind"], lead["booking_id"]) == ("booking", ctx.userdata.booking_id)
    assert lead["window_start"] == "2026-10-22T08:00:00-07:00"
    assert backends.leads.client.outbox.status(key)[0] == PENDING


async def test_the_booking_is_confirmed_aloud_by_code(backends):
    # Bug (agent simulation, 2026-10-25): the caller said "Yes, that's right. Thanks, that's
    # all, goodbye." Riley booked, then only said "Goodbye!": the caller never heard that the
    # booking went through. Like the safety script, the line every booked caller must hear is
    # said by the tool, and the model is told it's been said.
    ctx = context(OpenSession(), **READY)
    await offered_and_chosen(ctx)
    new_turn(ctx)
    out = await tools.book_appointment(ctx)
    assert ctx.session.said[-1] == "You're all set for tomorrow, 8-10 am."
    assert out["say"].startswith("They've just heard they're booked")
    # So the reply's own "You're all set..." is dropped this turn (RepeatedConfirmationGuard).
    assert ctx.userdata.confirmed_aloud


async def test_no_confirmation_is_said_when_the_booking_is_refused(backends):
    ctx = context(OpenSession(), **READY)
    await offered_and_chosen(ctx)
    await tools.book_appointment(ctx)  # same turn as the read-back: refused
    assert not any(line.startswith("You're all set") for line in ctx.session.said)


async def test_a_window_taken_meanwhile_is_reoffered(backends):
    ctx = context(OpenSession(), **READY)
    await offered_and_chosen(ctx)
    new_turn(ctx)
    for other_call in ("x", "y"):  # two other calls fill the window
        backends.calendar.book(
            key=other_call, call_id=other_call, window_id=FIRST, details={},
            now=NOW, priority=False,
        )  # fmt: skip
    out = await tools.book_appointment(ctx)
    assert (out["decision"], out["next_step"]) == ("OFFER_WINDOWS", "choose_window")
    assert out["say"].startswith("Tell them that window was just taken.")
    assert FIRST not in [w["id"] for w in out["windows"]]
    assert ctx.userdata.outcome is None


async def test_after_booking_the_tools_say_it_is_already_booked(backends):
    ctx = context(OpenSession(), **READY)
    await offered_and_chosen(ctx)
    new_turn(ctx)
    await tools.book_appointment(ctx)
    new_turn(ctx)  # "actually, can we do Friday?"
    out = await tools.find_windows(ctx, day="friday")
    assert out["decision"] == "ALREADY_BOOKED"


async def test_a_callback_request_queues_a_lead(backends):
    ctx = context(OpenSession())
    ctx.session.caller_says("can someone call me about my bill? I'm Jordan, 602-555-0142")
    out = await tools.request_callback(
        ctx, reason="billing", first_name="Jordan", callback_number="602-555-0142"
    )
    assert out["decision"] == "CALLBACK_READY"
    await backends.leads.drain(timeout=5)
    ((_, lead),) = backends.leads.client.outbox.pending()
    assert (lead["kind"], lead["callback_reason"]) == ("callback", "billing")


async def test_end_call_still_gets_a_goodbye_after_booking(backends):
    # Bug risk: no_second_goodbye used to mute end_call whenever an outcome was set, and a
    # booked call has one, but Riley hasn't said goodbye yet when the caller says "that's all".
    ctx = context(OpenSession(), **READY)
    await offered_and_chosen(ctx)
    new_turn(ctx)
    await tools.book_appointment(ctx)
    ev = SimpleNamespace(ctx=ctx, output=prompts.END_CALL_RESULT)
    await tools.no_second_goodbye(ev)
    assert ev.output == prompts.END_CALL_RESULT
    ctx.userdata.outcome = Outcome.OUT_OF_AREA  # a gate-ended call has said goodbye already
    await tools.no_second_goodbye(ev)
    assert ev.output is None
