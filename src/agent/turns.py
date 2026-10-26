"""Waiting for the rest of a number. Pure Python: main.py connects it to the session.

People give phone numbers in groups with pauses: "six oh two... five five five... oh one four
two". The turn detector can end the turn at the first pause, and Riley then answered half a
number and talked over the rest (audio simulation, 2026-10-25: three pieces, and the model
filled in digits nobody said). So while Riley is waiting for a number or a ZIP, a turn made of
fewer digits than it needs gets no reply yet: the caller can carry on, and their next turn is
joined to it. If they really have stopped, Riley answers what she has after a short wait.
"""

import asyncio
import re
from collections.abc import Callable

from agent.parsing import NUMBER_WORDS, digits_from_speech

DIGITS_NEEDED = {"callback_number": 10, "zip_code": 5}
# Words that can come with digits without making the turn about something else.
_FILLER = frozenset({
    "um", "uh", "er", "ah", "so", "it", "it's", "its", "is", "my", "the", "number", "zip",
    "code", "area", "and", "then", "yeah", "okay", "ok",
})  # fmt: skip
WAIT_SECONDS = 1.5  # after the caller stops talking, how long to wait for more digits
MAX_HOLDS = 2  # holds in a row; the third piece is answered, so a call can't stall here


def unfinished_digits(field: str | None, text: str) -> bool:
    """Whether the caller stopped partway through the digits Riley asked for: only digits (and
    filler) so far, but fewer than the field needs. "six oh two, is that enough?" is a question,
    not an unfinished number."""
    needed = DIGITS_NEEDED.get(field or "")
    if needed is None or not 0 < len(digits_from_speech(text)) < needed:
        return False
    words = re.findall(r"[a-z']+", text.lower())
    return all(w in NUMBER_WORDS or w in _FILLER for w in words)


class DigitHold:
    """Holds a reply while the caller is partway through a number.

    on_turn is called for every finished caller turn (Agent.on_user_turn_completed) and says
    whether to hold the reply, and what this turn's text is with any held words in front.
    on_caller_speaking / on_caller_silent follow the caller's voice activity: the wait for more
    digits runs only while they're quiet. reply(text) answers the held words when the wait
    runs out (main.py: session.generate_reply).
    """

    def __init__(
        self,
        expecting: Callable[[], str | None],
        reply: Callable[[str], object],
        wait_seconds: float = WAIT_SECONDS,
        max_holds: int = MAX_HOLDS,
    ) -> None:
        self._expecting = expecting
        self._reply = reply
        self._wait = wait_seconds
        self._max_holds = max_holds
        self._held = ""
        self._holds = 0
        self._timer: asyncio.TimerHandle | None = None

    def on_turn(self, text: str) -> tuple[bool, str]:
        self._stop_timer()
        if self._held:
            text = f"{self._held} {text}"
            self._held = ""
        if self._holds < self._max_holds and unfinished_digits(self._expecting(), text):
            self._held = text
            self._holds += 1
            self._start_timer()
            return True, text
        self._holds = 0
        return False, text

    def on_caller_speaking(self) -> None:
        self._stop_timer()  # they're carrying on

    def on_caller_silent(self) -> None:
        if self._held:
            self._start_timer()

    def _start_timer(self) -> None:
        self._stop_timer()
        self._timer = asyncio.get_running_loop().call_later(self._wait, self._give_up)

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _give_up(self) -> None:
        self._timer = None
        text, self._held = self._held, ""
        self._holds = 0
        self._reply(text)
