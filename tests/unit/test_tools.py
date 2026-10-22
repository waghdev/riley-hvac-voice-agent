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
    return SimpleNamespace(userdata=CallState(call_id="t"), session=session, speech_handle=None)


def test_acknowledging_while_the_session_closes_is_skipped_not_raised():
    # Bug (cloud call 1, 2026-10-22): a tool ran while the session was already closing, the
    # acknowledgement's say() raised, and the tool call failed with an exception.
    ctx = context(ClosingSession())
    assert tools._acknowledge(ctx) is None


def test_a_tool_result_still_comes_back_while_the_session_closes():
    ctx = context(ClosingSession())
    out = tools._run(ctx, tools.intake.record_service_location, zip_code="85016")
    assert out is not None and out["decision"] in ("MISSING", "READY_TO_BOOK")
