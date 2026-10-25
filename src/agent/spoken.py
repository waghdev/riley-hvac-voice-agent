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
from collections.abc import AsyncIterable, AsyncIterator, Callable

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
    # "between 12-2 pm" is "between noon and two", not "between noon to two" (debugger call,
    # 2026-10-22). The streamer keeps "between" in the same piece of text as the range.
    after_between = m.string[: m.start()].rstrip().lower().endswith("between")
    joiner = "and" if joiner.lower() == "and" or after_between else "to"
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

    Text with no digits goes out right away, except its last word: a partial word could still
    become "$8...", and a whole one ("between") can change how a number after it is said. From
    the word before the first digit or "$", text is held to the end of the sentence, so a number
    split across LLM chunks ("602-5" + "55-0142") is converted whole, with its lead-in word.
    """
    ready = ""
    while buffer:
        start = _NUMBER_START.search(buffer)
        if start is None:
            cut = buffer.rstrip().rfind(" ") + 1
            return ready + buffer[:cut], buffer[cut:]
        end = _SENTENCE_END.search(buffer, start.start())
        if end is None:
            if len(buffer) - start.start() > _MAX_HOLD:
                cut = buffer.rfind(" ") + 1
                return ready + buffer[:cut], buffer[cut:]
            lead_in = buffer[: start.start()].rstrip().rfind(" ") + 1
            return ready + buffer[:lead_in], buffer[lead_in:]
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


# --- Addressing the caller by name -------------------------------------------------------


class NameGuard:
    """A tts_text_transforms entry: Riley addresses the caller by name at most once per call.

    Bug (debugger and cloud calls): "Thanks, Jordan." turn after turn; a prompt rule held only
    about half the time. Vocative uses after the first ("Thanks, Jordan." / "Jordan, what's...")
    are dropped before TTS. Mentions inside a sentence ("I have your name as Jordan") are read-
    backs and stay. One instance per stream per call (TTS and the transcript each get one, see
    main.py); `get_name` returns the recorded first name, or None. The chat history keeps the
    model's words.
    """

    def __init__(self, get_name: Callable[[], str | None]) -> None:
        self._get_name = get_name
        self._used = False

    def __call__(self, text: AsyncIterable[str]) -> AsyncIterator[str]:
        return self._run(text)

    async def _run(self, text: AsyncIterable[str]) -> AsyncIterator[str]:
        pending = ""
        emitted_tail = (
            ""  # end of what's already gone out, so "Name," knows if it starts a sentence
        )
        async for chunk in text:
            name = self._get_name()
            buffer = pending + chunk
            if not name:
                pending = ""
                yield buffer
                emitted_tail = (emitted_tail + buffer)[-3:]
                continue
            # Hold back a tail that could still grow into ", Name" or "Name," on the next chunk.
            cut = len(buffer) - _holdback(buffer, name)
            ready, pending = buffer[:cut], buffer[cut:]
            if ready:
                out = self._apply(ready, name, emitted_tail)
                emitted_tail = (emitted_tail + out)[-3:]
                yield out
        if pending:
            name = self._get_name()
            yield self._apply(pending, name, emitted_tail) if name else pending

    def _apply(self, text: str, name: str, before: str) -> str:
        n = re.escape(name)

        def keep_first(m: re.Match[str], replacement: str) -> str:
            if not self._used:
                self._used = True
                return m.group(0)
            return replacement

        # "Thanks, Jordan." / "Got it, Jordan, and..." -> drop ", Jordan".
        text = re.sub(
            rf",\s*{n}(?=\s*[.!?,]|\s*$)", lambda m: keep_first(m, ""), text, flags=re.IGNORECASE
        )
        # "Jordan, what's..." at the start of a sentence -> "What's...".
        starts_sentence = before == "" or re.search(r"[.!?]\s*$", before) is not None
        pattern = (
            rf"(^|(?<=[.!?])\s+){n},\s*(\w)" if starts_sentence else rf"((?<=[.!?])\s+){n},\s*(\w)"
        )
        return re.sub(
            pattern,
            lambda m: keep_first(m, m.group(1) + m.group(2).upper()),
            text,
            flags=re.IGNORECASE,
        )


def _holdback(buffer: str, name: str) -> int:
    """How many trailing characters might be the start of ", Name" or "Name,"."""
    low = buffer.lower()
    patterns = [f", {name.lower()}", f",{name.lower()}", f"{name.lower()},"]
    for n in range(min(len(buffer), max(len(p) for p in patterns)), 0, -1):
        if any(p.startswith(low[-n:]) for p in patterns):
            return n
    return 0


# --- No second acknowledgement --------------------------------------------------------------

_ACK_WORDS = (
    r"(?:thanks|thank you|got it|okay|ok|alright|all right|great|perfect|sounds good|understood)"
)
# A complete opening acknowledgement: "Thanks.", "Thanks, Jordan.", "Okay," "Perfect!"
_LEADING_ACK = re.compile(rf"^\s*{_ACK_WORDS}(?:\s+so\s+much)?(?:,\s*[A-Za-z]+)?[.!,]\s*", re.I)
# Text that could still grow into one: "Tha", "Thanks", "Thanks, Jor"
_PARTIAL_ACK = re.compile(rf"^\s*{_ACK_WORDS}(?:\s+so(?:\s+much)?)?(?:,\s*[A-Za-z]*)?$", re.I)
_ACK_PHRASES = ("thanks", "thank you", "got it", "okay", "ok", "alright", "all right", "great",
                "perfect", "sounds good", "understood")  # fmt: skip
_LONE_WORD = re.compile(r"^[A-Za-z]+$")


class LeadingAckGuard:
    """A tts_text_transforms entry: once Riley has said "Got it." this turn (tools.py plays it
    while the LLM writes the reply), drop an acknowledgement the reply opens with.

    Bug (debugger calls): "Thanks." then "Thanks. What's the ZIP code?" in 2 of 2 runs, despite
    the prompt and a tool-result field. The spoken acknowledgement itself is a bare fixed line,
    so it passes untouched. Only the start of each reply is examined.
    """

    def __init__(self, acknowledged: Callable[[], bool]) -> None:
        self._acknowledged = acknowledged

    def __call__(self, text: AsyncIterable[str]) -> AsyncIterator[str]:
        return self._run(text)

    async def _run(self, text: AsyncIterable[str]) -> AsyncIterator[str]:
        head: str | None = ""  # None once the opening has been decided
        async for chunk in text:
            if head is None:
                yield chunk
                continue
            head += chunk
            decided = self._decide(head, final=False)
            if decided is not None:
                head = None
                if decided:
                    yield decided
        if head:
            yield self._decide(head, final=True) or ""

    def _decide(self, head: str, *, final: bool) -> str | None:
        """The text to send for this opening, or None if it's too early to tell."""
        m = _LEADING_ACK.match(head)
        if m and head[m.end() :].strip():
            # An acknowledgement followed by more of the reply.
            rest = head[m.end() :]
            if not final and _LONE_WORD.match(rest):
                # "Okay, Alex" may still become "Okay, Alex." with the name inside the
                # acknowledgement (first agent simulation, 2026-10-25).
                return None
            if not self._acknowledged():
                return head
            return rest[:1].upper() + rest[1:]
        if final:
            return head  # a bare line (Riley's own "Got it.") or something short: keep it
        if m or _PARTIAL_ACK.match(head) or self._is_word_prefix(head):
            return None  # could still be "Thanks. What's..." or the bare acknowledgement
        return head

    @staticmethod
    def _is_word_prefix(head: str) -> bool:
        start = head.lstrip().lower()
        return bool(start) and any(p.startswith(start) for p in _ACK_PHRASES)
