"""Numbers rewritten the way a person says them, before TTS (CLAUDE.md section 4)."""

import pytest

from agent.spoken import number_words, speak_numbers, speak_numbers_stream


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (0, "zero"),
        (7, "seven"),
        (15, "fifteen"),
        (40, "forty"),
        (89, "eighty-nine"),
        (100, "one hundred"),
        (120, "one hundred twenty"),
        (1200, "one thousand two hundred"),
        (25_050, "twenty-five thousand fifty"),
    ],
)
def test_number_words(n, words):
    assert number_words(n) == words


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        # Phone numbers in groups, zero as "oh".
        ("I have 602-555-0142.", "I have six oh two, five five five, oh one four two."),
        ("Call (602) 555-0142 back", "Call six oh two, five five five, oh one four two back"),
        ("It's 602.555.0142?", "It's six oh two, five five five, oh one four two?"),
        ("That's 6025550142, right?", "That's six oh two, five five five, oh one four two, right?"),
        ("+1 602 555 0142", "six oh two, five five five, oh one four two"),
        # ZIP codes digit by digit; ZIP+4 too.
        ("in 85016.", "in eight five oh one six."),
        ("85016-1234", "eight five oh one six, one two three four"),
        # Money.
        ("The visit is $89.", "The visit is eighty-nine dollars."),
        ("$89.50 total", "eighty-nine dollars and fifty cents total"),
        ("$1,200", "one thousand two hundred dollars"),
        # Times and windows.
        ("between 10 am and 12 pm", "between ten and noon"),
        ("10am-12pm works", "ten to noon works"),
        ("10\u201312 pm", "ten to noon"),  # en dash, as LLMs often write windows
        ("2-4 pm tomorrow", "two to four in the afternoon tomorrow"),
        ("from 2 to 4 PM", "from two to four in the afternoon"),
        ("at 8:00 am", "at eight in the morning"),
        ("at 4:30 pm", "at four thirty in the afternoon"),
        ("about 6:05 pm", "about six oh five in the evening"),
        ("10 am to 2 pm", "ten in the morning to two in the afternoon"),
        # Left alone: plain small numbers read fine, and words are never touched.
        ("about 2 minutes", "about 2 minutes"),
        ("one or two short sentences", "one or two short sentences"),
        ("", ""),
    ],
)
def test_speak_numbers(text, spoken):
    assert speak_numbers(text) == spoken


async def collect(chunks: list[str]) -> list[str]:
    async def source():
        for c in chunks:
            yield c

    return [out async for out in speak_numbers_stream(source())]


async def test_a_number_split_across_chunks_is_converted_whole():
    chunks = ["Got it, your number is 602-5", "55-01", "42. Is that right?"]
    out = await collect(chunks)
    assert "".join(out) == speak_numbers("".join(chunks))
    assert "six oh two, five five five, oh one four two" in "".join(out)


async def test_text_without_numbers_is_not_held_back():
    # Latency: digit-free text must reach TTS before the stream ends, word by word.
    out = await collect(["Sorry to ", "hear that. What's ", "your first name?"])
    assert len(out) >= 2
    assert "".join(out) == "Sorry to hear that. What's your first name?"


async def test_text_after_a_number_flows_again_once_the_sentence_ends():
    out = await collect(["It's $89. ", "The technician ", "will explain more."])
    assert "".join(out) == "It's eighty-nine dollars. The technician will explain more."
    assert out[0].startswith("It's eighty-nine dollars.")


async def test_a_trailing_number_is_flushed_at_the_end():
    out = await collect(["Your ZIP is 8501", "6"])
    assert "".join(out) == "Your ZIP is eight five oh one six"


@pytest.mark.parametrize(
    ("hour", "spoken"),
    [
        (8, "Thursday, eight to ten in the morning"),
        (10, "Thursday, ten to noon"),
        (12, "Thursday, noon to two in the afternoon"),
        (14, "Thursday, two to four in the afternoon"),
        (16, "Thursday, four to six in the evening"),
    ],
)
def test_every_booking_window_is_spoken_naturally(hour, spoken):
    # The labels calendar.py writes for the LLM, as TTS will say them.
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo

    from agent.calendar import Window

    start = datetime(2026, 10, 22, hour, tzinfo=ZoneInfo("America/Phoenix"))  # a Thursday
    label = Window(start, start + timedelta(hours=2)).when(date(2026, 10, 19))
    assert speak_numbers(label) == spoken
