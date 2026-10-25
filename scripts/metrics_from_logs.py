"""Turn "turn metrics" log lines into metrics JSONL, for the deployed agent (its disk isn't kept).

    lk agent logs > agent.log          # stop it once the calls are done
    uv run python scripts/metrics_from_logs.py agent.log >> metrics/cloud.jsonl
    uv run python scripts/latency_report.py metrics/cloud.jsonl

In production mode the agent logs JSON, and main.py attaches each latency record to its
"turn metrics" line. This keeps only the record's own fields, dropping the logger's.
"""

import json
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

# The fields TurnPairer and client_timing_record write (src/agent/metrics.py).
RECORD_KEYS = (
    "ts",
    "call_id",
    "channel",
    "kind",
    "turn",
    "eou_delay_ms",
    "stt_final_ms",
    "llm_ttft_ms",
    "tts_ttfb_ms",
    "e2e_ms",
    "greeting_start_ms",
    "click_to_speech_ms",
    "connect_to_speech_ms",
)
KINDS = ("turn", "greeting", "client_greeting")


def extract(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    # `lk agent logs` replays recent lines every time it reconnects, so the same record can appear
    # more than once in a capture. Each greeting or turn is counted once.
    seen: set[tuple[Any, ...]] = set()
    for line in lines:
        start = line.find("{")  # the CLI may prefix lines with its own text
        if start < 0:
            continue
        try:
            entry = json.loads(line[start:])
        except ValueError:
            continue
        if entry.get("message") != "turn metrics" or entry.get("kind") not in KINDS:
            continue
        key = (entry.get("call_id"), entry.get("kind"), entry.get("turn"))
        if key in seen:
            continue
        seen.add(key)
        yield {k: entry[k] for k in RECORD_KEYS if k in entry}


def main(argv: list[str]) -> None:
    for path in argv:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        for record in extract(lines):
            print(json.dumps(record))


if __name__ == "__main__":
    main(sys.argv[1:])
