"""Silence handling: check in a couple of times, then close politely.

Pure asyncio with injected say/close callables, so it's unit-tested without a LiveKit session.
main.py feeds it the session's user-state changes and every caller turn.
"""

import asyncio
from collections.abc import Awaitable, Callable


class SilenceMonitor:
    def __init__(
        self,
        *,
        say: Callable[[str], Awaitable[object]],  # speak a line, resolve when it has played
        close: Callable[[str], Awaitable[object]],  # speak a final line and end the session
        wait_seconds: float,
        prompts: int,
        still_there: str,
        goodbye: str,
    ) -> None:
        self._say = say
        self._close = close
        self._wait = wait_seconds
        self._prompts = prompts
        self._still_there = still_there
        self._goodbye = goodbye
        self._task: asyncio.Task[None] | None = None
        self._closing = False

    def on_user_state(self, state: str) -> None:
        """Feed every user_state_changed event. "away" means silence on both sides."""
        if state == "away":
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._check_in())
        else:
            self._cancel()

    def on_caller_turn(self) -> None:
        """Feed every caller message. Typed input never changes the user state, so this is
        the signal that works for text and speech alike."""
        self._cancel()

    def stop(self) -> None:
        """The session is closing: cancel unconditionally."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def _cancel(self) -> None:
        # Once the goodbye has started, finish it; a caller talking over it doesn't undo it.
        if self._task is not None and not self._closing:
            self._task.cancel()
            self._task = None

    async def _check_in(self) -> None:
        for _ in range(self._prompts):
            await self._say(self._still_there)
            await asyncio.sleep(self._wait)
        self._closing = True
        await self._close(self._goodbye)
