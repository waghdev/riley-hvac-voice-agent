"""The greeting as one pre-rendered clip, so its voice can't change partway through.

Bug (Dev's cloud call, 2026-10-21): live TTS streams each sentence separately, and Aura-2 read
"This call may be recorded for quality." in a noticeably different voice. The greeting is fixed
text, so scripts/make_greeting_audio.py renders it once, in one request, into assets/greeting.wav,
with a manifest recording the exact text and voice. Riley plays the clip only if both still
match; otherwise she falls back to live TTS, so stale audio never plays. It also takes TTS out of
the greeting's start time.

No LiveKit imports: main.py turns the PCM into audio frames.
"""

import hashlib
import io
import json
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.config import REPO_ROOT

ASSETS = REPO_ROOT / "assets"
MANIFEST = "greeting.json"
CLIP = "greeting.wav"


@dataclass(frozen=True)
class GreetingClip:
    pcm: bytes  # 16-bit little-endian mono samples
    sample_rate: int


def manifest_for(text: str, voice: str, wav: bytes) -> dict[str, Any]:
    """What scripts/make_greeting_audio.py writes next to the clip."""
    return {"text": text, "voice": voice, "file": CLIP, "sha256": hashlib.sha256(wav).hexdigest()}


def load_greeting(text: str, voice: str, assets: Path = ASSETS) -> GreetingClip | None:
    """The clip if it's this exact greeting in this voice, else None (use live TTS)."""
    try:
        manifest = json.loads((assets / MANIFEST).read_text(encoding="utf-8"))
        if manifest.get("text") != text or manifest.get("voice") != voice:
            return None
        wav = (assets / manifest["file"]).read_bytes()
        if hashlib.sha256(wav).hexdigest() != manifest.get("sha256"):
            return None
        with wave.open(io.BytesIO(wav)) as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                return None
            return GreetingClip(pcm=w.readframes(w.getnframes()), sample_rate=w.getframerate())
    except (OSError, ValueError, KeyError, wave.Error):
        return None
