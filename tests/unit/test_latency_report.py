import json

import pytest

from latency_report import load_records, percentile, summarize, to_markdown


@pytest.mark.parametrize(
    ("values", "q", "expected"),
    [
        ([500.0], 0.5, 500.0),
        ([500.0], 0.9, 500.0),
        ([100.0, 200.0, 300.0, 400.0], 0.5, 200.0),  # nearest rank, not 250 interpolated
        ([400.0, 100.0, 300.0, 200.0], 0.5, 200.0),  # order doesn't matter
        ([float(v) for v in range(1, 11)], 0.9, 9.0),
        ([float(v) for v in range(1, 11)], 0.91, 10.0),
    ],
)
def test_percentile_is_nearest_rank(values, q, expected):
    assert percentile(values, q) == expected


def test_percentile_of_nothing_is_an_error():
    with pytest.raises(ValueError):
        percentile([], 0.5)


def turn(call, channel="web", **stages):
    return {"kind": "turn", "call_id": call, "channel": channel, **stages}


def test_summary_counts_calls_and_turns_per_channel():
    summary = summarize(
        [
            {"kind": "greeting", "call_id": "a", "channel": "web", "greeting_start_ms": 900.0},
            turn("a", e2e_ms=800.0),
            turn("a", e2e_ms=1000.0),
            turn("b", e2e_ms=700.0),
            turn("c", channel="phone", e2e_ms=1100.0),
        ]
    )
    assert len(summary["web"]["calls"]) == 2
    assert summary["web"]["turns"] == 3
    assert summary["web"]["values"]["e2e_ms"] == [800.0, 1000.0, 700.0]
    assert summary["web"]["values"]["greeting_start_ms"] == [900.0]
    assert summary["phone"]["turns"] == 1


def test_missing_stages_are_left_out_not_counted_as_zero():
    summary = summarize([turn("a", e2e_ms=800.0, tts_ttfb_ms=None)])
    assert "tts_ttfb_ms" not in summary["web"]["values"]


def test_markdown_puts_web_first_and_shows_p50_p90_and_n():
    md = to_markdown(
        summarize(
            [
                turn("c", channel="console", e2e_ms=2000.0),
                turn("a", e2e_ms=800.0),
                turn("a", e2e_ms=1000.0),
            ]
        )
    )
    assert md.index("### web") < md.index("### console")
    assert "| Total response | 800 ms | 1,000 ms | 2 |" in md
    assert "| TTS first audio | - | - | 0 |" in md


def test_empty_input_says_so():
    assert to_markdown(summarize([])) == "No metrics recorded yet."


def test_load_records_skips_blank_lines(tmp_path):
    path = tmp_path / "m.jsonl"
    path.write_text(json.dumps(turn("a", e2e_ms=1.0)) + "\n\n", encoding="utf-8")
    assert len(load_records([path])) == 1
