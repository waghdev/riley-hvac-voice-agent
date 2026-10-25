"""Fixed lines play from pre-rendered clips, and only if a clip is the current text and voice.

Bug (Dev's cloud call, 2026-10-21): live TTS streams each sentence separately, and Aura-2 read
"This call may be recorded for quality." in a noticeably different voice.
"""

import io
import json
import math
import struct
import wave

import pytest

from agent.clips import load_clip, manifest_for
from agent.config import DEFAULT_TTS_VOICE
from make_audio_clips import fixed_lines

TEXT = "Thanks for calling. This call may be recorded for quality."
VOICE = "aura-2-andromeda-en"


def wav_bytes(channels: int = 1, rate: int = 24000, seconds: float = 0.1) -> bytes:
    n = int(rate * seconds)
    samples = [int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(n)]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", s) * channels for s in samples))
    return buf.getvalue()


@pytest.fixture
def assets(tmp_path):
    data = wav_bytes()
    (tmp_path / "greeting.wav").write_bytes(data)
    (tmp_path / "greeting.json").write_text(json.dumps(manifest_for("greeting", TEXT, VOICE, data)))
    return tmp_path


def test_matching_clip_loads_as_16_bit_mono_pcm(assets):
    clip = load_clip("greeting", TEXT, VOICE, assets)
    assert clip is not None
    assert clip.sample_rate == 24000
    assert len(clip.pcm) == 2400 * 2  # 0.1 s of 16-bit samples


@pytest.mark.parametrize(
    ("text", "voice"),
    [
        (TEXT + " Changed.", VOICE),  # greeting edited in business.yaml, clip not re-rendered
        (TEXT, "aura-2-thalia-en"),  # voice changed
    ],
)
def test_stale_clip_is_never_played(assets, text, voice):
    assert load_clip("greeting", text, voice, assets) is None


def test_tampered_audio_is_rejected(assets):
    (assets / "greeting.wav").write_bytes(wav_bytes(seconds=0.2))
    assert load_clip("greeting", TEXT, VOICE, assets) is None


def test_stereo_audio_is_rejected(tmp_path):
    data = wav_bytes(channels=2)
    (tmp_path / "greeting.wav").write_bytes(data)
    (tmp_path / "greeting.json").write_text(json.dumps(manifest_for("greeting", TEXT, VOICE, data)))
    assert load_clip("greeting", TEXT, VOICE, tmp_path) is None


def test_missing_clip_falls_back(tmp_path):
    assert load_clip("greeting", TEXT, VOICE, tmp_path) is None


@pytest.mark.parametrize(("name", "text"), fixed_lines().items())
def test_committed_clips_are_the_current_lines_in_the_default_voice(name, text):
    # Fails when a line (business.yaml's greeting, prompts.SERVICE_UNAVAILABLE) or the default
    # voice changes, until scripts/make_audio_clips.py is rerun.
    assert load_clip(name, text, DEFAULT_TTS_VOICE) is not None
