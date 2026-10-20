"""config/business.yaml must match docs/business.md, the human-written source of truth.

These are drift checks: if someone edits one file and not the other, CI fails.
"""

import itertools
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = (ROOT / "docs" / "business.md").read_text(encoding="utf-8")
CONFIG = yaml.safe_load((ROOT / "config" / "business.yaml").read_text(encoding="utf-8"))


def collapse_whitespace(text: str) -> str:
    # The spec wraps long lines and the YAML folds them, so compare word sequences only.
    return " ".join(text.split())


def spec_section(heading: str) -> str:
    """Text under a '## heading' in business.md, up to the next '## '."""
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", SPEC, re.M | re.S)
    assert match, f"section '## {heading}' not found in docs/business.md"
    return match.group(1)


@pytest.mark.parametrize("script", ["greeting", "safety", "price_question"])
def test_exact_scripts_match_spec_word_for_word(script):
    assert collapse_whitespace(CONFIG["scripts"][script]) in collapse_whitespace(SPEC)


def test_service_area_zips_match_spec():
    spec_zips = set(re.findall(r"\b\d{5}\b", spec_section("Service area (ZIP codes)")))
    assert set(CONFIG["service_area"]["zip_codes"]) == spec_zips


def test_zips_are_five_digit_strings():
    # Unquoted 85003 in YAML parses as an int; a ZIP like 01234 would lose its leading zero.
    for zip_code in CONFIG["service_area"]["zip_codes"]:
        assert isinstance(zip_code, str) and re.fullmatch(r"\d{5}", zip_code), zip_code


def test_offered_categories_match_spec():
    spec_ids = set(re.findall(r"^\| `(\w+)` \|", spec_section("Services offered"), re.M))
    assert set(CONFIG["services"]["offered"]) == spec_ids


def test_offered_and_not_offered_do_not_overlap():
    services = CONFIG["services"]
    assert not set(services["offered"]) & set(services["not_offered"])


def test_urgency_categories_are_offered():
    urgency = CONFIG["urgency"]
    offered = set(CONFIG["services"]["offered"])
    assert set(urgency["no_cooling_categories"]) | set(urgency["no_heat_categories"]) <= offered


def test_diagnostic_fee_matches_spec():
    pricing = spec_section("Pricing (the only numbers Riley may say)")
    assert f"${CONFIG['pricing']['diagnostic_fee']}" in pricing


def test_booking_windows_are_ordered_and_do_not_overlap():
    windows = [(w["start"], w["end"]) for w in CONFIG["booking"]["windows"]]
    for start, end in windows:
        assert re.fullmatch(r"\d{2}:\d{2}", start) and re.fullmatch(r"\d{2}:\d{2}", end)
        assert start < end  # zero-padded HH:MM strings sort like times
    for (_, prev_end), (next_start, _) in itertools.pairwise(windows):
        assert prev_end <= next_start


def test_no_sunday_appointments():
    assert "sunday" not in CONFIG["booking"]["days"]
