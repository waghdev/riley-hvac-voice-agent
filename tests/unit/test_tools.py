"""tools.py behavior that doesn't need a live session, using a stand-in RunContext."""

from types import SimpleNamespace

from agent import tools
from agent.state import CallState


class ClosingSession:
    """Like AgentSession once shutdown has started: say() refuses."""

    def __init__(self) -> None:
        self.options: list[dict] = []

    def say(self, *args, **kwargs):
        raise RuntimeError("AgentSession is closing, cannot use say()")

    def update_options(self, **kwargs) -> None:
        self.options.append(kwargs)


def context(session) -> SimpleNamespace:
    handle = SimpleNamespace(add_done_callback=lambda cb: None)  # the turn's speech handle
    return SimpleNamespace(userdata=CallState(call_id="t"), session=session, speech_handle=handle)


def test_acknowledging_while_the_session_closes_is_skipped_not_raised():
    # Bug (cloud call 1, 2026-10-22): a tool ran while the session was already closing, the
    # acknowledgement's say() raised, and the tool call failed with an exception.
    ctx = context(ClosingSession())
    assert tools._acknowledge(ctx) is None


def test_a_tool_result_still_comes_back_while_the_session_closes():
    ctx = context(ClosingSession())
    out = tools._run(ctx, tools.intake.record_service_location, zip_code="85016")
    assert out is not None and out["decision"] in ("MISSING", "READY_TO_BOOK")


class OpenSession:
    """A running session: records what's said and option changes."""

    def __init__(self) -> None:
        self.said: list[str] = []
        self.options: list[dict] = []

    def say(self, line, **kwargs):
        self.said.append(line)
        return SimpleNamespace(add_done_callback=lambda cb: None)

    def update_options(self, **kwargs) -> None:
        self.options.append(kwargs)


def test_tools_are_ignored_once_the_call_is_decided():
    # Bug (cloud call, 2026-10-22): after an out-of-area ZIP ended the call, a stray "two."
    # reached the model, which re-recorded it as a ZIP while Riley was saying goodbye.
    ctx = context(OpenSession())
    tools._run(ctx, tools.intake.record_service_location, zip_code="80139")  # out of area
    assert ctx.userdata.outcome is not None
    before = (ctx.userdata.zip_code, dict(ctx.userdata.failed_attempts))
    out = tools._run(ctx, tools.intake.record_service_location, zip_code="two")
    assert out is None  # no reply, nothing recorded
    assert (ctx.userdata.zip_code, ctx.userdata.failed_attempts) == before


def test_a_safety_report_still_plays_after_the_call_is_decided():
    session = OpenSession()
    ctx = context(session)
    tools._run(ctx, tools.intake.record_service_location, zip_code="80139")
    tools._run(ctx, tools.intake.report_safety_hazard, signal="gas_smell")
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
