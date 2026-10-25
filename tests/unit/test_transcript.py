"""The transcript shows what the caller hears (main.Riley.transcription_node)."""

from collections.abc import AsyncIterator

from agent.main import Riley
from agent.spoken import LeadingAckGuard, NameGuard


async def stream(*chunks: str) -> AsyncIterator[str]:
    for chunk in chunks:
        yield chunk


async def transcript(riley: Riley, *chunks: str) -> str:
    return "".join([c async for c in riley.transcription_node(stream(*chunks), None)])


def riley(acknowledged: bool = True) -> Riley:
    return Riley(
        transcript_transforms=[LeadingAckGuard(lambda: acknowledged), NameGuard(lambda: "Alex")]
    )


async def test_no_second_acknowledgement_in_the_transcript():
    # Bug (first agent simulation, 2026-10-25): the tool's spoken "Okay." then "Okay, Alex.
    # What's the best callback number?" in the transcript. Callers hear the acknowledgement
    # once (LeadingAckGuard runs before TTS), but the web page's transcript and the simulation
    # judge read the model's words, and the judge flagged the repeat.
    said = await transcript(riley(), "Okay, Alex", ". What's the best ", "callback number?")
    assert said == "What's the best callback number?"


async def test_an_opening_acknowledgement_stays_when_none_was_spoken():
    said = await transcript(riley(acknowledged=False), "Thanks. What's your ZIP code?")
    assert said == "Thanks. What's your ZIP code?"


async def test_the_name_at_most_once_in_the_transcript_too():
    r = riley(acknowledged=False)
    assert await transcript(r, "Alex, what's your ZIP code?") == "Alex, what's your ZIP code?"
    assert await transcript(r, "Alex, is that right?") == "Is that right?"


async def test_digits_stay_digits_in_the_transcript():
    # Numbers are spelled out for TTS only (speak_numbers_stream); a transcript reads better
    # with digits.
    said = await transcript(riley(acknowledged=False), "Is 602-555-0142 the best number?")
    assert said == "Is 602-555-0142 the best number?"


async def test_without_transforms_the_transcript_is_the_model_text():
    said = await transcript(Riley(), "Okay, Alex. What's your ZIP?")
    assert said == "Okay, Alex. What's your ZIP?"
