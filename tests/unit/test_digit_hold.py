"""Riley waits for the rest of a number instead of answering half of it (turns.py).

Bug (audio simulation, 2026-10-25): asked for a number, the caller said "Six zero two." then
paused; the turn ended, Riley started "Could you...", and the number arrived in three pieces
("Five." / "O. One four two."). The model then recorded digits nobody said.
"""

import asyncio

import pytest

from agent.turns import DigitHold, unfinished_digits


@pytest.mark.parametrize(
    ("field", "text", "unfinished"),
    [
        ("callback_number", "Six zero two.", True),
        ("callback_number", "six oh two, five five five", True),
        ("callback_number", "um, it's 602", True),
        ("callback_number", "six oh two five five five oh one four two", False),  # complete
        ("callback_number", "602-555-0142", False),
        ("callback_number", "six oh two, is that the area code you need?", False),  # a question
        ("callback_number", "I'd rather not give it out", False),  # no digits
        ("zip_code", "eight five oh", True),
        ("zip_code", "eight five oh one six", False),
        ("first_name", "Six", False),  # not waiting for digits
        (None, "six oh two", False),
    ],
)
def test_unfinished_digits(field, text, unfinished):
    assert unfinished_digits(field, text) is unfinished


class Replies:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def __call__(self, text: str) -> None:
        self.texts.append(text)


def hold(expecting: str | None = "callback_number", wait: float = 0.05):
    replies = Replies()
    return DigitHold(lambda: expecting, reply=replies, wait_seconds=wait), replies


async def test_a_partial_number_is_held_and_joined_to_the_rest():
    h, replies = hold()
    assert h.on_turn("Six zero two.") == (True, "Six zero two.")
    h.on_caller_speaking()  # they carry on: no reply in between
    await asyncio.sleep(0.1)
    assert h.on_turn("five five five, oh one four two") == (
        False,
        "Six zero two. five five five, oh one four two",
    )
    assert replies.texts == []


async def test_if_the_caller_stops_partway_riley_answers_what_she_has():
    h, replies = hold()
    assert h.on_turn("Six zero two.")[0]
    await asyncio.sleep(0.1)
    assert replies.texts == ["Six zero two."]
    # That reply carried the held words, so the next turn starts fresh.
    assert h.on_turn("six oh two five five five oh one four two") == (
        False,
        "six oh two five five five oh one four two",
    )


async def test_the_wait_starts_again_when_the_caller_stops_talking():
    h, replies = hold(wait=0.1)
    h.on_turn("Six zero two.")
    await asyncio.sleep(0.06)
    h.on_caller_speaking()
    h.on_caller_silent()  # a false start: the wait begins again from here
    await asyncio.sleep(0.06)
    assert replies.texts == []
    await asyncio.sleep(0.1)
    assert replies.texts == ["Six zero two."]


async def test_only_digits_are_held():
    h, _ = hold()
    assert h.on_turn("I'd rather not give out my number.") == (
        False,
        "I'd rather not give out my number.",
    )
    h2, _ = hold(expecting="first_name")
    assert h2.on_turn("Six") == (False, "Six")


async def test_it_holds_at_most_twice_in_a_row():
    h, _ = hold()
    assert h.on_turn("six")[0]
    assert h.on_turn("oh")[0]
    held, text = h.on_turn("two")
    assert (held, text) == (False, "six oh two")  # answered, so it can't stall the call
