"""Loads config/business.yaml. No LiveKit imports, so tests and gates can use it directly."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BUSINESS_YAML = REPO_ROOT / "config" / "business.yaml"
# Deepgram Aura-2 voice, chosen by Dev by listening (docs/decisions.md); TTS_VOICE overrides it.
# Here rather than in main.py so the greeting-clip test can check it without importing LiveKit.
DEFAULT_TTS_VOICE = "aura-2-andromeda-en"


def load_business(path: Path = BUSINESS_YAML) -> dict[str, Any]:
    """The raw YAML, used to build prompts."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class BusinessConfig:
    """The facts the gates decide with, typed and read-only, built from business.yaml."""

    zip_codes: frozenset[str]
    service_area: str  # how Riley describes it when declining, e.g. "central Phoenix"
    offered: Mapping[str, str]  # category id -> description
    not_offered: Mapping[str, str]
    safety_signals: frozenset[str]
    safety_script: str  # said word for word
    no_cooling_categories: frozenset[str]
    no_heat_categories: frozenset[str]
    indoor_temp_priority_f: int
    vulnerable_occupants: frozenset[str]
    required_fields: tuple[str, ...]  # in the order Riley asks for them
    callback_number_digits: int
    callback_reasons: frozenset[str]
    callback_promise: str
    max_attempts_per_field: int = 2  # CLAUDE.md section 4: after two misses, offer a callback

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> "BusinessConfig":
        return cls(
            zip_codes=frozenset(raw["service_area"]["zip_codes"]),
            service_area=raw["service_area"]["description"],
            offered=MappingProxyType(dict(raw["services"]["offered"])),
            not_offered=MappingProxyType(dict(raw["services"]["not_offered"])),
            safety_signals=frozenset(raw["safety"]["signals"]),
            safety_script=raw["scripts"]["safety"],
            no_cooling_categories=frozenset(raw["urgency"]["no_cooling_categories"]),
            no_heat_categories=frozenset(raw["urgency"]["no_heat_categories"]),
            indoor_temp_priority_f=int(raw["urgency"]["indoor_temp_priority_f"]),
            vulnerable_occupants=frozenset(raw["urgency"]["vulnerable_occupants"]),
            required_fields=tuple(raw["readiness"]["required_fields"]),
            callback_number_digits=int(raw["readiness"]["callback_number_digits"]),
            callback_reasons=frozenset(raw["callback"]["reasons"]),
            callback_promise=raw["callback"]["promise"],
        )


def load_config(path: Path = BUSINESS_YAML) -> BusinessConfig:
    return BusinessConfig.from_raw(load_business(path))
