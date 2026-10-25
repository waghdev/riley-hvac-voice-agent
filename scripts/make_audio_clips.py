"""Render Riley's fixed lines once each, in single TTS requests, into assets/<name>.wav + manifest.

    uv run python scripts/make_audio_clips.py

Rerun whenever one of the lines (config/business.yaml's greeting, prompts.SERVICE_UNAVAILABLE) or
the voice changes; a unit test fails until you do. Uses DEEPGRAM_API_KEY and TTS_VOICE from .env
(about 250 characters of Deepgram credit).
"""

import json
import os
import urllib.request

from dotenv import load_dotenv

from agent import prompts
from agent.clips import ASSETS, load_clip, manifest_for
from agent.config import DEFAULT_TTS_VOICE, REPO_ROOT, load_business

SAMPLE_RATE = 24000  # the Deepgram plugin's default output rate, so a clip matches live speech


def fixed_lines() -> dict[str, str]:
    """Clip name -> the exact text it says."""
    return {
        "greeting": prompts.greeting(load_business()),
        "unavailable": prompts.SERVICE_UNAVAILABLE,
    }


def render(text: str, voice: str) -> bytes:
    request = urllib.request.Request(
        f"https://api.deepgram.com/v1/speak?model={voice}"
        f"&encoding=linear16&sample_rate={SAMPLE_RATE}&container=wav",
        data=json.dumps({"text": text}).encode(),
        headers={
            "Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    voice = os.getenv("TTS_VOICE") or DEFAULT_TTS_VOICE
    ASSETS.mkdir(exist_ok=True)
    for name, text in fixed_lines().items():
        if load_clip(name, text, voice) is not None:
            print(f"{name}: up to date")
            continue
        wav = render(text, voice)
        (ASSETS / f"{name}.wav").write_bytes(wav)
        manifest = manifest_for(name, text, voice, wav)
        manifest_text = json.dumps(manifest, indent=2) + "\n"
        (ASSETS / f"{name}.json").write_text(manifest_text, encoding="utf-8")
        clip = load_clip(name, text, voice)
        assert clip is not None, f"{name}: the clip just written doesn't load; check the format"
        seconds = len(clip.pcm) / 2 / clip.sample_rate
        print(f"{name}: wrote {voice}, {clip.sample_rate} Hz, {seconds:.1f} s")


if __name__ == "__main__":
    main()
