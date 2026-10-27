"""Turn spoken or written details into the digits the gates check. Pure functions, no LiveKit.

The LLM passes what it heard: sometimes digits ("85016"), sometimes words ("eight five oh one
six"), sometimes a mix with filler ("my zip is ..."). Normalizing that is a format check, so it
lives in code, not in the prompt.
"""

import re
from collections.abc import Iterable

_UNITS = {
    "zero": 0, "oh": 0, "o": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}  # fmt: skip
_TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # fmt: skip
_TENS = {
    "twenty": 2, "thirty": 3, "forty": 4, "fifty": 5, "sixty": 6, "seventy": 7, "eighty": 8,
    "ninety": 9,
}  # fmt: skip
_REPEATS = {"double": 2, "triple": 3}
# Every word digits_from_speech reads as (part of) a number.
NUMBER_WORDS = frozenset(_UNITS) | frozenset(_TEENS) | frozenset(_TENS) | frozenset(_REPEATS)


def digits_from_speech(text: str) -> str:
    """Every digit in the text, in order, reading number words as digits.

    "eight five oh one six" -> "85016"; "double five" -> "55"; "eighty five" -> "85";
    "sixteen" -> "16". Words that aren't numbers ("my zip is") are skipped.
    """
    tokens = re.findall(r"[a-z]+|\d", text.lower())
    out: list[str] = []
    repeat = 1
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _REPEATS:
            repeat = _REPEATS[tok]
            i += 1
            continue
        if tok.isdigit():
            digits = tok
        elif tok in _UNITS:
            digits = str(_UNITS[tok])
        elif tok in _TEENS:
            digits = str(_TEENS[tok])
        elif tok in _TENS:
            # "eighty five" is 85; "twenty" alone is 20.
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
            if nxt in _UNITS and _UNITS[nxt] > 0:
                digits = f"{_TENS[tok]}{_UNITS[nxt]}"
                i += 1
            else:
                digits = f"{_TENS[tok]}0"
        else:
            i += 1
            continue
        out.append(digits * repeat)
        repeat = 1
        i += 1
    return "".join(out)


def normalize_zip(text: str) -> str | None:
    """A five-digit ZIP, or None. ZIP+4 is accepted; the gate uses the first five digits."""
    digits = digits_from_speech(text)
    if len(digits) in (5, 9):
        return digits[:5]
    return None


def normalize_phone(text: str) -> str | None:
    """A ten-digit US number, or None. A leading country code 1 is dropped."""
    digits = digits_from_speech(text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    # North American numbering: area code and exchange both start with 2-9.
    if digits[0] in "01" or digits[3] in "01":
        return None
    return digits


def digits_heard(digits: str, caller_turns: Iterable[str]) -> bool:
    """Whether the caller said these digits, in this order, gaps allowed.

    The same rule as said_by_caller, for numbers: asked for ten digits, the model filled in the
    ones it missed (audio simulation, 2026-10-25: "Six zero two." / "Five." / "O. One four two."
    recorded with two digits nobody said). Gaps are allowed so a number given in pieces, or
    corrected ("it ends oh one eight four"), still counts; a digit nobody said can't be matched.
    """
    heard = iter("".join(digits_from_speech(turn) for turn in caller_turns))
    return all(d in heard for d in digits)  # `in` advances the iterator: a subsequence test


def _words(text: str) -> str:
    """Lowercase words only: "My mom's 82-ish!" -> "my mom s 82 ish"."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


# Words callers use for the people around them. The model has saved one as the caller's first
# name: "mom" from "my eighty one year old mom is here with me" (audio simulation, 2026-10-27).
_NOT_NAMES = frozenset({
    "mom", "mum", "mother", "mama", "mommy", "dad", "father", "papa", "daddy", "parent",
    "wife", "husband", "spouse", "partner", "son", "daughter", "kid", "child", "baby",
    "grandma", "grandmother", "grandpa", "grandfather", "sister", "brother", "aunt", "uncle",
    "friend", "neighbor", "neighbour", "roommate", "landlord", "tenant", "boss", "sir", "maam",
    "caller", "customer", "homeowner", "owner",
})  # fmt: skip


def name_heard(name: str, caller_turns: Iterable[str]) -> bool:
    """Whether `name` is a name the caller gave: every word of it said by them, whole or spelled
    out ("D. A. N. A."), and none of them a word for someone else ("mom").

    The same idea as said_by_caller, for names: asked to fill first_name, the model has used
    a word from the caller's sentence that isn't their name.
    """
    words = _words(name).split()
    if not words or any(w in _NOT_NAMES for w in words):
        return False
    said = [_words(turn).split() for turn in caller_turns]
    return all(any(w in turn or _spelled(w, turn) for turn in said) for w in words)


def _spelled(word: str, turn: list[str]) -> bool:
    """Whether the turn spells `word` letter by letter: speech-to-text writes a spelled name
    as single letters ("D. A. N. A." or "D-A-N-A"), which _words splits into ["d", "a", ...]."""
    letters = list(word)
    n = len(letters)
    return n > 1 and any(turn[i : i + n] == letters for i in range(len(turn) - n + 1))


# What callers say to show they're listening, or to agree, without picking anything: "mm-hmm",
# "okay", "sure, that works for me". Times, days and "the first one" aren't in it.
_HUMS = re.compile(r"[mh]+|u+h+|h+u+h+|u+h*m+|a+h+|o+h+")
_ASSENT = frozenset({
    "yes", "yeah", "yep", "yup", "ya", "yah", "ok", "okay", "okey", "sure", "right", "alright",
    "all", "fine", "good", "great", "perfect", "cool", "sounds", "that", "s", "ll", "works",
    "work", "will", "for", "me", "please", "thanks", "thank", "you", "so", "well",
})  # fmt: skip


def only_assent(text: str) -> bool:
    """Whether a turn is nothing but "I'm listening" or "yes": every word a hum or an assent.

    Bug (audio simulation, 2026-10-27): two windows offered, the caller said "Mhmm." while
    Riley spoke, and the model chose the first window for them.
    """
    words = _words(text).split()
    return bool(words) and all(w in _ASSENT or _HUMS.fullmatch(w) for w in words)


def said_by_caller(quote: str | None, caller_turns: Iterable[str]) -> bool:
    """Whether the caller really said `quote` (case and punctuation ignored).

    For facts the LLM tends to invent: asked to fill an optional field, it has made one up
    (debugger call, 2026-10-22: vulnerable_occupant="infant" for "my AC stopped cooling"). The
    model passes the caller's own words as evidence, and code checks them against the
    transcript. An invented quote isn't there, so the claim is dropped.
    """
    if quote is None or len(_words(quote)) < 3:
        return False
    # Padded with spaces so only whole words match: "mom" isn't found in "momentarily".
    wanted = f" {_words(quote)} "
    return any(wanted in f" {_words(turn)} " for turn in caller_turns)
