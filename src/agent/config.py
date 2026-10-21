"""Loads config/business.yaml. No LiveKit imports, so tests and gates can use it directly."""

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BUSINESS_YAML = REPO_ROOT / "config" / "business.yaml"
# Deepgram Aura-2 voice, chosen by Dev by listening (docs/decisions.md); TTS_VOICE overrides it.
# Here rather than in main.py so the greeting-clip test can check it without importing LiveKit.
DEFAULT_TTS_VOICE = "aura-2-andromeda-en"


def load_business(path: Path = BUSINESS_YAML) -> dict[str, Any]:
    # A plain dict for now; M2 replaces this with a typed BusinessConfig for the gates.
    return yaml.safe_load(path.read_text(encoding="utf-8"))
