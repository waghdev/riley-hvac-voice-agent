"""Render the greeting once, in a single TTS request, into assets/greeting.wav plus a manifest.

    uv run python scripts/make_greeting_audio.py

Rerun whenever the greeting in config/business.yaml or the voice changes; a unit test fails until
you do. Uses DEEPGRAM_API_KEY and TTS_VOICE from .env (about 150 characters of Deepgram credit).
"""

import json
import os
import urllib.request

from dotenv import load_dotenv

from agent.config import DEFAULT_TTS_VOICE, REPO_ROOT, load_business
from agent.greeting_audio import ASSETS, CLIP, MANIFEST, load_greeting, manifest_for

SAMPLE_RATE = 24000  # the Deepgram plugin's default output rate, so the clip matches live speech


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    text = load_business()["scripts"]["greeting"]
    voice = os.getenv("TTS_VOICE") or DEFAULT_TTS_VOICE
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
        wav = response.read()

    ASSETS.mkdir(exist_ok=True)
    (ASSETS / CLIP).write_bytes(wav)
    manifest = manifest_for(text, voice, wav)
    (ASSETS / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    clip = load_greeting(text, voice)
    assert clip is not None, "the clip just written doesn't load; check the WAV format"
    seconds = len(clip.pcm) / 2 / clip.sample_rate
    print(f"wrote {ASSETS / CLIP}: {voice}, {clip.sample_rate} Hz, {seconds:.1f} s")


if __name__ == "__main__":
    main()
