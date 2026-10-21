"""Rewrite numbers the way a person says them, before the text reaches TTS (CLAUDE.md section 4).

    602-555-0142   -> six oh two, five five five, oh one four two
    85016          -> eight five oh one six
    $89            -> eighty-nine dollars
    10 am - 12 pm  -> ten to noon;  2-4 pm -> two to four in the afternoon

Only what TTS hears changes; the transcript keeps the digits. A tested code step, not a prompt
instruction. Pure functions, no LiveKit: main.py passes speak_numbers_stream to the session's
tts_text_transforms.
"""

import re
from collections.abc import AsyncIterable, AsyncIterator

_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen",
]  # fmt: skip
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_DIGIT = ["oh", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


def number_words(n: int) -> str:
    """0..999,999 in words: 89 -> "eighty-nine", 1200 -> "one thousand two hundred"."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_ONES[hundreds]} hundred" + (f" {number_words(rest)}" if rest else "")
    thousands, rest = divmod(n, 1000)
    return f"{number_words(thousands)} thousand" + (f" {number_words(rest)}" if rest else "")


def _digits(s: str) -> str:
    """Digit by digit, zero as "oh": "016" -> "oh one six"."""
    return " ".join(_DIGIT[int(d)] for d in s)


_PHONE = re.compile(
    r"(?<![\d$])(?:\+?1[\s.-]?)?\(?([2-9]\d{2})\)?[\s.-]?([2-9]\d{2})[\s.-]?(\d{4})(?!\d)"
)
_MONEY = re.compile(r"\$(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?")
_PERIOD = r"(am|pm|a\.m\.|p\.m\.)"
_TIME = r"(\d{1,2})(?::(\d{2}))?"
_RANGE = re.compile(
    # "\u2013" is an en dash (U+2013): LLMs often write windows with one.
    rf"\b{_TIME}\s*{_PERIOD}?\s*(-|\u2013|to|and)\s*{_TIME}\s*{_PERIOD}(?![a-z])",
    re.IGNORECASE,
)
_SINGLE_TIME = re.compile(rf"\b{_TIME}\s*{_PERIOD}(?![a-z])", re.IGNORECASE)
_ZIP = re.compile(r"(?<![\d$.,])(\d{5})(?:-(\d{4}))?(?![\d,])")


def _phone(m: re.Match[str]) -> str:
    return ", ".join(_digits(g) for g in m.groups())


def _money(m: re.Match[str]) -> str:
    dollars = int(m.group(1).replace(",", ""))
    spoken = f"{number_words(dollars)} dollar{'' if dollars == 1 else 's'}"
    cents = int(m.group(2) or 0)
    if cents:
        spoken += f" and {number_words(cents)} cent{'' if cents == 1 else 's'}"
    return spoken


def _is_pm(period: str | None) -> bool | None:
    return None if period is None else period.lower().startswith("p")


def _clock(hour: str, minute: str | None, pm: bool | None) -> str:
    """ "4", "30" -> "four thirty"; 12 pm -> "noon"; 12 am -> "midnight"."""
    h, mins = int(hour), int(minute or 0)
    if h == 12 and not mins and pm is not None:
        return "noon" if pm else "midnight"
    words = number_words(h)
    if mins:
        words += f" oh {_ONES[mins]}" if mins < 10 else f" {number_words(mins)}"
    return words


def _part_of_day(hour: str, pm: bool | None) -> str:
    h = int(hour)
    if pm is None or h == 12:
        return ""
    if not pm:
        return " in the morning"
    return " in the afternoon" if h < 5 else " in the evening"


def _range(m: re.Match[str]) -> str:
    h1, m1, p1, joiner, h2, m2, p2 = m.groups()
    end_pm = _is_pm(p2)
    start_pm = _is_pm(p1) if p1 else end_pm  # "2-4 pm": the start shares the end's period
    joiner = "and" if joiner.lower() == "and" else "to"
    start, end = _clock(h1, m1, start_pm), _clock(h2, m2, end_pm)
    if end in ("noon", "midnight") or start_pm == end_pm:
        # One part of day for the whole window: "ten to noon", "two to four in the afternoon".
        return f"{start} {joiner} {end}{_part_of_day(h2, end_pm)}"
    return f"{start}{_part_of_day(h1, start_pm)} {joiner} {end}{_part_of_day(h2, end_pm)}"


def _single_time(m: re.Match[str]) -> str:
    hour, minute, period = m.groups()
    pm = _is_pm(period)
    return _clock(hour, minute, pm) + _part_of_day(hour, pm)


def _zip(m: re.Match[str]) -> str:
    return _digits(m.group(1)) + (f", {_digits(m.group(2))}" if m.group(2) else "")


def speak_numbers(text: str) -> str:
    # Order matters: phone numbers first, so their digits can't be read as a ZIP or a time.
    text = _PHONE.sub(_phone, text)
    text = _MONEY.sub(_money, text)
    text = _RANGE.sub(_range, text)
    text = _SINGLE_TIME.sub(_single_time, text)
    return _ZIP.sub(_zip, text)


# --- Streaming -------------------------------------------------------------------------------

_NUMBER_START = re.compile(r"[\d$]")
_SENTENCE_END = re.compile(r"[.!?](?=\s)")
_MAX_HOLD = 160  # characters; a safety valve so a sentence with no ending never stalls speech


def _split_ready(buffer: str) -> tuple[str, str]:
    """Split the buffer into text that's safe to convert and send now, and text to hold.

    Text with no digits goes out right away (up to the last space, since a partial word could
    still become "$8..."). From the first digit or "$", text is held to the end of the sentence,
    so a number split across LLM chunks ("602-5" + "55-0142") is converted whole.
    """
    ready = ""
    while buffer:
        start = _NUMBER_START.search(buffer)
        if start is None:
            cut = buffer.rfind(" ") + 1
            return ready + buffer[:cut], buffer[cut:]
        end = _SENTENCE_END.search(buffer, start.start())
        if end is None:
            if len(buffer) - start.start() > _MAX_HOLD:
                cut = buffer.rfind(" ") + 1
                return ready + buffer[:cut], buffer[cut:]
            return ready + buffer[: start.start()], buffer[start.start() :]
        ready += buffer[: end.end()]
        buffer = buffer[end.end() :]
    return ready, ""


async def speak_numbers_stream(text: AsyncIterable[str]) -> AsyncIterator[str]:
    """speak_numbers for streamed LLM output (a LiveKit tts_text_transforms entry)."""
    pending = ""
    async for chunk in text:
        ready, pending = _split_ready(pending + chunk)
        if ready:
            yield speak_numbers(ready)
    if pending:
        yield speak_numbers(pending)
