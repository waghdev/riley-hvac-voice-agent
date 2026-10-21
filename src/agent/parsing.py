"""Turn spoken or written details into the digits the gates check. Pure functions, no LiveKit.

The LLM passes what it heard: sometimes digits ("85016"), sometimes words ("eight five oh one
six"), sometimes a mix with filler ("my zip is ..."). Normalizing that is a format check, so it
lives in code, not in the prompt.
"""

import re

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
