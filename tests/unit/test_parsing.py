"""Turning what the caller said (as the LLM heard it) into digits the gates can check."""

import pytest

from agent.parsing import digits_from_speech, normalize_phone, normalize_zip


@pytest.mark.parametrize(
    ("said", "digits"),
    [
        ("eight five zero one six", "85016"),
        ("eight five oh one six", "85016"),
        ("Eight, five, O, one, six.", "85016"),
        ("85016", "85016"),
        ("850 16", "85016"),
        ("six oh two five five five oh one four two", "6025550142"),
        ("six oh two, double five five, oh one four two", "6025550142"),
        ("triple five", "555"),
        ("eighty five oh sixteen", "850" + "16"),
        ("twenty", "20"),
        ("my zip is 85016", "85016"),
        ("", ""),
    ],
)
def test_digits_from_speech(said, digits):
    assert digits_from_speech(said) == digits


@pytest.mark.parametrize(
    ("said", "zip_code"),
    [
        ("85016", "85016"),
        ("85016-1234", "85016"),  # ZIP+4: the first five digits
        ("850161234", "85016"),  # ZIP+4 without the dash
        ("eight five zero zero three", "85003"),  # CLAUDE.md section 6 edge case
        ("eight five oh one six dash one two three four", "85016"),
        ("my zip code is 85016", "85016"),
        ("8501", None),  # too short
        ("850166", None),  # six digits: not a ZIP or ZIP+4
        ("Phoenix", None),
        ("", None),
    ],
)
def test_normalize_zip(said, zip_code):
    assert normalize_zip(said) == zip_code


@pytest.mark.parametrize(
    ("said", "number"),
    [
        ("602-555-0142", "6025550142"),
        ("(602) 555-0142", "6025550142"),
        ("+1 602 555 0142", "6025550142"),  # country code dropped
        ("1-602-555-0142", "6025550142"),
        ("six oh two, five five five, oh one four two", "6025550142"),
        ("6025550142", "6025550142"),
        ("555-0142", None),  # no area code
        ("602-555-01425", None),  # too long
        ("102-555-0142", None),  # area codes can't start with 0 or 1
        ("602-155-0142", None),  # exchanges can't start with 0 or 1
        ("", None),
    ],
)
def test_normalize_phone(said, number):
    assert normalize_phone(said) == number
