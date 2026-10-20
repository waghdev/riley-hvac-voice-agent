"""metrics/*.jsonl -> Markdown latency table: p50/p90 per stage, one table per channel.

    uv run python scripts/latency_report.py            # all files in metrics/
    uv run python scripts/latency_report.py metrics/2026-10-21.jsonl

Percentiles are nearest-rank, so every number in the table is a latency that was actually
observed, not an interpolation between two turns.
"""

import json
import math
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# Record key -> row label, in pipeline order (CLAUDE.md section 8).
STAGES = {
    "eou_delay_ms": "End of utterance",
    "stt_final_ms": "STT final transcript",
    "llm_ttft_ms": "LLM first token",
    "tts_ttfb_ms": "TTS first audio",
    "e2e_ms": "Total response",
}
CHANNEL_ORDER = ["web", "phone", "console"]  # web is the headline


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile: the smallest observed value with at least q of values <= it."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    return ordered[max(math.ceil(q * len(ordered)) - 1, 0)]


def load_records(paths: Iterable[Path]) -> list[dict[str, Any]]:
    records = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per channel: call and turn counts, plus the observed values for each stage."""
    by_channel: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"calls": set(), "turns": 0, "values": defaultdict(list)}
    )
    for r in records:
        ch = by_channel[r.get("channel", "unknown")]
        ch["calls"].add(r.get("call_id"))
        if r.get("kind") == "turn":
            ch["turns"] += 1
            for key in STAGES:
                if r.get(key) is not None:  # a missing stage is unknown, not zero
                    ch["values"][key].append(r[key])
        elif r.get("kind") == "greeting" and r.get("greeting_start_ms") is not None:
            ch["values"]["greeting_start_ms"].append(r["greeting_start_ms"])
    return dict(by_channel)


def to_markdown(summary: dict[str, dict[str, Any]]) -> str:
    if not summary:
        return "No metrics recorded yet."
    rank = {c: i for i, c in enumerate(CHANNEL_ORDER)}  # unknown channels go last
    channels = sorted(summary, key=lambda c: (rank.get(c, len(rank)), c))
    out = []
    for channel in channels:
        ch = summary[channel]
        out.append(f"### {channel}: {len(ch['calls'])} calls, {ch['turns']} turns\n")
        out.append("| Stage | p50 | p90 | n |")
        out.append("| --- | ---: | ---: | ---: |")
        rows = [*STAGES.items(), ("greeting_start_ms", "Greeting start after session start")]
        for key, label in rows:
            values = ch["values"].get(key, [])
            if values:
                p50, p90 = percentile(values, 0.5), percentile(values, 0.9)
                out.append(f"| {label} | {p50:,.0f} ms | {p90:,.0f} ms | {len(values)} |")
            else:
                out.append(f"| {label} | - | - | 0 |")
        out.append("")
    return "\n".join(out)


def main(argv: list[str]) -> None:
    paths = [Path(a) for a in argv] or sorted(Path("metrics").glob("*.jsonl"))
    print(to_markdown(summarize(load_records(paths))))


if __name__ == "__main__":
    main(sys.argv[1:])
