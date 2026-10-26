"""After tools.py says "You're all set for <window>.", the reply doesn't say it again.

Bug (audio simulation, 2026-10-25): "You're all set for tomorrow, 10 am-12 pm." from code, then
"You're all set for tomorrow between 10 am and 12 pm. Is there anything else I can help you
with?" from the model, despite the tool result saying the caller had just heard it.
"""

import pytest

from agent.spoken import RepeatedConfirmationGuard


async def run(chunks: list[str], said: bool = True) -> str:
    guard = RepeatedConfirmationGuard(lambda: said)

    async def source():
        for c in chunks:
            yield c

    return "".join([out async for out in guard(source())])


@pytest.mark.parametrize(
    ("reply", "heard"),
    [
        (
            "You're all set for tomorrow between 10 am and 12 pm. Is there anything else?",
            "Is there anything else?",
        ),
        (
            "You are all set for tomorrow. Anything else I can help with?",
            "Anything else I can help with?",
        ),
        ("You're booked for today, 2 to 4 pm! Anything else?", "Anything else?"),
        # "a.m." isn't the end of the sentence.
        (
            "You're all set for 10 a.m. to 12 p.m. Is there anything else?",
            "Is there anything else?",
        ),
    ],
)
async def test_a_repeated_confirmation_is_dropped(reply, heard):
    assert await run([reply]) == heard


async def test_split_across_chunks():
    chunks = [
        "You're all",
        " set for tomorrow between 10 am",
        " and 12 pm. Is there",
        " anything else?",
    ]
    assert await run(chunks) == "Is there anything else?"


async def test_a_reply_that_is_only_the_repeat_says_nothing():
    assert await run(["You're all set for tomorrow, 10 am-12 pm."]) == ""


@pytest.mark.parametrize(
    "reply",
    [
        "Is there anything else I can help you with?",
        "Your technician will call ahead. Anything else?",
        "You're welcome! Anything else?",
    ],
)
async def test_other_replies_pass_untouched(reply):
    assert await run([reply]) == reply


async def test_nothing_is_dropped_when_code_said_no_confirmation():
    reply = "You're all set for tomorrow. Anything else?"
    assert await run([reply], said=False) == reply
