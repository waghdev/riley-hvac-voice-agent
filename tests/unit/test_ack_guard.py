"""After a spoken "Got it.", the reply doesn't open with another acknowledgement.

Bug (debugger calls, 2026-10-21): the tool says "Thanks." while the LLM writes its reply, and
the reply began "Thanks. What's the ZIP code..." anyway, in 2 of 2 runs, despite the prompt and
a field in the tool result. So it's removed in code, before TTS.
"""

import pytest

from agent.prompts import ACKNOWLEDGEMENTS
from agent.spoken import LeadingAckGuard


async def run(guard: LeadingAckGuard, chunks: list[str]) -> str:
    async def source():
        for c in chunks:
            yield c

    return "".join([out async for out in guard(source())])


def guard_for(acknowledged: bool) -> LeadingAckGuard:
    return LeadingAckGuard(lambda: acknowledged)


@pytest.mark.parametrize(
    ("reply", "heard"),
    [
        ("Thanks. What's the ZIP code?", "What's the ZIP code?"),
        ("Got it. I have your number as 602-555-0142.", "I have your number as 602-555-0142."),
        ("Thanks, Jordan. What's your number?", "What's your number?"),
        ("Okay, what's the ZIP code?", "What's the ZIP code?"),
        ("Perfect! And the ZIP code?", "And the ZIP code?"),
        ("Thank you. Where do you need service?", "Where do you need service?"),
    ],
)
async def test_a_leading_acknowledgement_is_dropped_after_one_was_spoken(reply, heard):
    assert await run(guard_for(True), [reply]) == heard


async def test_split_across_chunks(reply="Thanks. What's the ZIP code?"):
    assert await run(guard_for(True), ["Tha", "nks. Wh", "at's the ZIP code?"]) == (
        "What's the ZIP code?"
    )


async def test_a_chunk_ending_on_the_name_waits_for_the_rest():
    # Bug (first agent simulation, 2026-10-25): with a chunk ending "Okay, Alex", "Okay," was
    # taken as the whole acknowledgement, and "Alex. What's the best callback number?" went
    # out. The name still belongs to the acknowledgement once its "." arrives.
    chunks = ["Okay, Alex", ". What's the best ", "callback number?"]
    assert await run(guard_for(True), chunks) == "What's the best callback number?"


async def test_a_one_word_reply_after_an_acknowledgement_still_comes_out():
    assert await run(guard_for(True), ["Okay, ", "great"]) == "Great"


@pytest.mark.parametrize("line", ACKNOWLEDGEMENTS)
async def test_the_acknowledgement_itself_is_never_touched(line):
    assert await run(guard_for(True), [line]) == line


@pytest.mark.parametrize(
    "reply",
    [
        "Thanks for calling Kestrel Comfort.",  # "thanks for", not an acknowledgement
        "I'm sorry to hear that. What's your first name?",
        "Okay so you said eight five oh one six?",  # no punctuation after "Okay"
    ],
)
async def test_other_openings_are_kept(reply):
    assert await run(guard_for(True), [reply]) == reply


async def test_nothing_is_dropped_when_no_acknowledgement_was_spoken():
    assert await run(guard_for(False), ["Thanks. What's the ZIP code?"]) == (
        "Thanks. What's the ZIP code?"
    )


async def test_only_the_start_of_a_reply_is_affected():
    reply = "What's your number? Thanks. Got it."
    assert await run(guard_for(True), [reply]) == reply
