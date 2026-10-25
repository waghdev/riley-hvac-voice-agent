"""An unrecoverable model error ends the call politely, once (main.close_on_fatal_error)."""

import asyncio
from types import SimpleNamespace

from agent import prompts
from agent.main import UNAVAILABLE_CLIP, close_on_fatal_error


def error(recoverable: bool) -> SimpleNamespace:
    return SimpleNamespace(error=SimpleNamespace(recoverable=recoverable), source=object())


async def test_a_fatal_error_says_the_line_and_hangs_up_once():
    # Bug (debugger call, 2026-10-25): the line played, then dead air, because livekit-agents
    # 1.8.8 only closes the session after three unrecoverable errors in a row.
    calls: list[tuple] = []

    async def end_with(line, by, clip=None):
        calls.append((line, by, clip))

    on_error = close_on_fatal_error(end_with)
    on_error(error(recoverable=True))  # retried by the SDK: nothing to do
    on_error(error(recoverable=False))
    on_error(error(recoverable=False))  # already hanging up
    await asyncio.sleep(0)  # let the hang-up task run
    assert calls == [(prompts.SERVICE_UNAVAILABLE, "error", UNAVAILABLE_CLIP)]


def test_the_line_is_pre_rendered_so_it_plays_without_tts():
    assert UNAVAILABLE_CLIP is not None
