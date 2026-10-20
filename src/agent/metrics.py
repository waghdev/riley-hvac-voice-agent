"""Per-turn latency records: one JSON line per turn under metrics/ (gitignored).

LiveKit attaches a MetricsReport (a dict of seconds) to every ChatMessage. The caller's message
carries the end-of-turn and transcription delays; Riley's reply that follows carries LLM time to
first token, TTS time to first audio, and end-to-end latency. TurnPairer joins the two into one
record. No LiveKit imports, so this is unit-tested without a session.
"""

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# MetricsReport key -> record key (milliseconds). Stage names follow CLAUDE.md section 8.
USER_FIELDS = {
    "end_of_turn_delay": "eou_delay_ms",  # caller stops speaking -> turn committed
    "transcription_delay": "stt_final_ms",  # caller stops speaking -> final transcript
}
ASSISTANT_FIELDS = {
    "llm_node_ttft": "llm_ttft_ms",
    "tts_node_ttfb": "tts_ttfb_ms",
    "e2e_latency": "e2e_ms",  # caller stops speaking -> first agent audio (the headline number)
}


def _to_ms(report: Mapping[str, Any], fields: Mapping[str, str]) -> dict[str, float | None]:
    return {
        out: round(report[key] * 1000, 1) if report.get(key) is not None else None
        for key, out in fields.items()
    }


@dataclass
class TurnPairer:
    call_id: str
    channel: str  # "web", "phone" or "console"; the report keeps them separate
    session_started_at: float  # unix seconds, taken just before session.start()

    def __post_init__(self) -> None:
        self._pending_user: Mapping[str, Any] | None = None
        self._turns = 0
        self._greeted = False

    def add(self, role: str, report: Mapping[str, Any]) -> dict[str, Any] | None:
        """Feed one ChatMessage's role and metrics. Returns a record when one is complete."""
        if role == "user":
            # If the caller speaks twice before Riley answers, the later message is the one
            # Riley's reply is timed against.
            self._pending_user = report
            return None
        if role != "assistant":
            return None

        base = {"ts": round(time.time(), 3), "call_id": self.call_id, "channel": self.channel}

        if not self._greeted:
            self._greeted = True
            started = report.get("started_speaking_at")
            greeting_ms = (
                round((started - self.session_started_at) * 1000, 1)
                if started is not None
                else None
            )
            return {**base, "kind": "greeting", "greeting_start_ms": greeting_ms}

        if self._pending_user is None:
            # Riley spoke without the caller speaking first (a silence check-in or the time
            # limit line). There is no response latency to measure.
            return None

        self._turns += 1
        record = {
            **base,
            "kind": "turn",
            "turn": self._turns,
            **_to_ms(self._pending_user, USER_FIELDS),
            **_to_ms(report, ASSISTANT_FIELDS),
        }
        self._pending_user = None
        return record


class JsonlWriter:
    """Appends records to metrics/<UTC date>.jsonl."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{time.strftime('%Y-%m-%d', time.gmtime())}.jsonl"

    def write(self, record: Mapping[str, Any]) -> None:
        # One short line per turn, so a plain synchronous append is fine inside the event loop.
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
