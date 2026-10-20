"""SilenceMonitor: "Are you still there?" twice, then a polite close (CLAUDE.md section 4)."""

import asyncio

import pytest

from agent.silence import SilenceMonitor

WAIT = 0.02  # seconds; the real value is 7


class FakeSession:
    def __init__(self) -> None:
        self.said: list[str] = []
        self.closed_with: str | None = None

    async def say(self, line: str) -> None:
        self.said.append(line)

    async def close(self, line: str) -> None:
        self.closed_with = line


@pytest.fixture
def session():
    return FakeSession()


@pytest.fixture
def monitor(session):
    return SilenceMonitor(
        say=session.say,
        close=session.close,
        wait_seconds=WAIT,
        prompts=2,
        still_there="Are you still there?",
        goodbye="Goodbye.",
    )


async def test_two_unanswered_check_ins_then_a_polite_close(monitor, session):
    monitor.on_user_state("away")
    await asyncio.sleep(WAIT * 4)
    assert session.said == ["Are you still there?", "Are you still there?"]
    assert session.closed_with == "Goodbye."


async def test_caller_speaking_cancels_the_check_in(monitor, session):
    monitor.on_user_state("away")
    await asyncio.sleep(WAIT / 2)
    monitor.on_user_state("speaking")
    await asyncio.sleep(WAIT * 4)
    assert session.said == ["Are you still there?"]
    assert session.closed_with is None


async def test_caller_turn_cancels_the_check_in_even_if_state_still_says_away(monitor, session):
    # Bug found in a debugger call (2026-10-20): typed input never changes the user state, so
    # Riley kept checking in and hung up on a caller who was mid-conversation.
    monitor.on_user_state("away")
    await asyncio.sleep(WAIT / 2)
    monitor.on_caller_turn()
    await asyncio.sleep(WAIT * 4)
    assert session.closed_with is None


async def test_goodbye_is_not_cancelled_once_it_starts(session):
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_close(line: str) -> None:
        started.set()
        await release.wait()
        session.closed_with = line

    monitor = SilenceMonitor(
        say=session.say,
        close=slow_close,
        wait_seconds=WAIT,
        prompts=1,
        still_there="Are you still there?",
        goodbye="Goodbye.",
    )
    monitor.on_user_state("away")
    await asyncio.wait_for(started.wait(), timeout=1)
    monitor.on_user_state("speaking")  # caller talks over the goodbye
    release.set()
    await asyncio.sleep(WAIT)
    assert session.closed_with == "Goodbye."


async def test_silence_after_recovering_starts_a_fresh_check_in(monitor, session):
    monitor.on_user_state("away")
    await asyncio.sleep(WAIT / 2)
    monitor.on_user_state("speaking")
    monitor.on_user_state("away")
    await asyncio.sleep(WAIT * 4)
    assert session.closed_with == "Goodbye."


async def test_repeated_away_events_do_not_start_a_second_check_in(monitor, session):
    monitor.on_user_state("away")
    monitor.on_user_state("away")
    await asyncio.sleep(WAIT * 4)
    assert session.said.count("Are you still there?") == 2


async def test_stop_cancels_everything_when_the_session_closes(monitor, session):
    monitor.on_user_state("away")
    monitor.stop()
    await asyncio.sleep(WAIT * 4)
    assert session.closed_with is None
