"""Riley addresses the caller by name at most once per call.

Bug (debugger and cloud calls, 2026-10-20/21): "Thanks, Jordan." on turn after turn. A prompt
rule held only about half the time at Gemini's default temperature, so it's enforced in code.
"""

import pytest

from agent.spoken import NameGuard


async def run(guard: NameGuard, chunks: list[str]) -> str:
    async def source():
        for c in chunks:
            yield c

    return "".join([out async for out in guard(source())])


@pytest.fixture
def guard():
    return NameGuard(lambda: "Jordan")


async def test_the_first_use_is_kept_and_later_ones_dropped(guard):
    assert await run(guard, ["Thanks, Jordan. What's your number?"]) == (
        "Thanks, Jordan. What's your number?"
    )
    assert await run(guard, ["Thanks, Jordan. And the ZIP code?"]) == "Thanks. And the ZIP code?"
    assert await run(guard, ["Got it, Jordan, and when works?"]) == "Got it, and when works?"


@pytest.mark.parametrize(
    ("second_reply", "spoken"),
    [
        ("Jordan, what's the ZIP code?", "What's the ZIP code?"),  # sentence-initial
        ("Okay. Jordan, one more thing.", "Okay. One more thing."),
        ("Perfect, jordan!", "Perfect!"),  # case-insensitive
        ("Thanks, Jordan", "Thanks"),  # at the very end
    ],
)
async def test_vocative_forms_after_the_first_are_dropped(guard, second_reply, spoken):
    await run(guard, ["Thanks, Jordan."])
    assert await run(guard, [second_reply]) == spoken


async def test_non_vocative_mentions_are_kept_for_read_backs(guard):
    await run(guard, ["Thanks, Jordan."])
    text = "I have your name as Jordan, and the number as six oh two."
    assert await run(guard, [text]) == text


async def test_a_name_split_across_chunks_is_still_caught(guard):
    await run(guard, ["Thanks, Jordan."])
    assert await run(guard, ["Great, Jor", "dan. What's", " the ZIP?"]) == "Great. What's the ZIP?"


async def test_names_containing_the_name_are_not_touched(guard):
    await run(guard, ["Thanks, Jordan."])
    assert await run(guard, ["Thanks, Jordana."]) == "Thanks, Jordana."


async def test_without_a_known_name_text_passes_through():
    guard = NameGuard(lambda: None)
    assert await run(guard, ["Thanks, Jordan.", " Thanks, Jordan."]) == (
        "Thanks, Jordan. Thanks, Jordan."
    )
