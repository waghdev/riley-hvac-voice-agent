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


def test_lines_replayed_by_a_reconnect_are_counted_once():
    # `lk agent logs` replays recent lines on every reconnect, so a capture can repeat records.
    turn = log_line(
        message="turn metrics", call_id="c3", channel="web", kind="turn", turn=1, e2e_ms=900.0
    )
    greeting = log_line(
        message="turn metrics", call_id="c3", channel="web", kind="greeting", greeting_start_ms=1.0
    )
    next_turn = log_line(
        message="turn metrics", call_id="c3", channel="web", kind="turn", turn=2, e2e_ms=800.0
    )
    records = list(extract([greeting, turn, greeting, turn, next_turn]))
    assert [(r["kind"], r.get("turn")) for r in records] == [
        ("greeting", None),
        ("turn", 1),
        ("turn", 2),
    ]


def test_keeps_the_browser_greeting_measurement():
    line = json.dumps(
        {"message": "turn metrics", "level": "INFO", "kind": "client_greeting", "call_id": "c1",
         "channel": "web", "ts": 1.0, "click_to_speech_ms": 3000, "connect_to_speech_ms": 1400}
    )  # fmt: skip
    assert list(extract([line])) == [
        {"ts": 1.0, "call_id": "c1", "channel": "web", "kind": "client_greeting",
         "click_to_speech_ms": 3000, "connect_to_speech_ms": 1400}
    ]  # fmt: skip
