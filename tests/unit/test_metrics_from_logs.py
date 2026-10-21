import json

from metrics_from_logs import extract


def log_line(**fields):
    base = {"level": "INFO", "name": "riley", "pid": 7, "timestamp": "2026-10-21T12:00:00+00:00"}
    return json.dumps({**base, **fields})


def test_keeps_turn_and_greeting_records_and_drops_logger_fields():
    lines = [
        log_line(
            message="turn metrics",
            call_id="c1",
            channel="web",
            kind="greeting",
            greeting_start_ms=900.0,
        ),
        log_line(
            message="turn metrics",
            call_id="c1",
            channel="web",
            kind="turn",
            turn=1,
            eou_delay_ms=300.0,
            e2e_ms=850.0,
        ),
    ]
    records = list(extract(lines))
    assert records[0] == {
        "call_id": "c1",
        "channel": "web",
        "kind": "greeting",
        "greeting_start_ms": 900.0,
    }
    assert records[1]["e2e_ms"] == 850.0
    assert "pid" not in records[1] and "level" not in records[1]


def test_ignores_other_messages_plain_text_and_broken_json():
    lines = [
        log_line(message="registered worker", agent_name="riley"),
        "starting build...",
        '{"message": "turn metrics", "kind": "turn"',  # truncated line
    ]
    assert list(extract(lines)) == []


def test_tolerates_a_prefix_before_the_json():
    line = "2026-10-21 12:00:00 instance-a | " + log_line(
        message="turn metrics", call_id="c2", channel="web", kind="turn", turn=1, e2e_ms=900.0
    )
    (record,) = extract([line])
    assert record["call_id"] == "c2"
