"""Fixed lines as pre-rendered clips: the greeting, and the line for when something breaks.

Greeting bug (Dev's cloud call, 2026-10-21): live TTS streams each sentence separately, and
Aura-2 read "This call may be recorded for quality." in a noticeably different voice. A fixed line
can be rendered once, in one request, by scripts/make_audio_clips.py into assets/<name>.wav, with
a manifest recording the exact text and voice. A clip plays only if both still match; otherwise
Riley falls back to live TTS, so stale audio never plays. It also takes TTS out of the greeting's
start time, and lets the "unavailable" line play even when TTS is what failed.

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


@dataclass(frozen=True)
class Clip:
    pcm: bytes  # 16-bit little-endian mono samples
    sample_rate: int


def manifest_for(name: str, text: str, voice: str, wav: bytes) -> dict[str, Any]:
    """What scripts/make_audio_clips.py writes next to assets/<name>.wav."""
    return {
        "text": text,
        "voice": voice,
        "file": f"{name}.wav",
        "sha256": hashlib.sha256(wav).hexdigest(),
    }


def load_clip(name: str, text: str, voice: str, assets: Path = ASSETS) -> Clip | None:
    """The clip if it's this exact text in this voice, else None (use live TTS)."""
    try:
        manifest = json.loads((assets / f"{name}.json").read_text(encoding="utf-8"))
        if manifest.get("text") != text or manifest.get("voice") != voice:
            return None
        wav = (assets / manifest["file"]).read_bytes()
        if hashlib.sha256(wav).hexdigest() != manifest.get("sha256"):
            return None
        with wave.open(io.BytesIO(wav)) as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                return None
            return Clip(pcm=w.readframes(w.getnframes()), sample_rate=w.getframerate())
    except (OSError, ValueError, KeyError, wave.Error):
        return None
