import json

import pytest

from agent.metrics import JsonlWriter, TurnPairer

START = 1_000.0


@pytest.fixture
def pairer():
    return TurnPairer(call_id="call-1", channel="console", session_started_at=START)


def test_first_assistant_message_is_the_greeting(pairer):
    record = pairer.add("assistant", {"started_speaking_at": START + 0.8421})
    assert record["kind"] == "greeting"
    assert record["greeting_start_ms"] == 842.1
    assert record["call_id"] == "call-1" and record["channel"] == "console"


def test_greeting_without_timestamp_records_none(pairer):
    assert pairer.add("assistant", {})["greeting_start_ms"] is None


def test_user_then_assistant_makes_one_turn_with_all_five_stages(pairer):
    pairer.add("assistant", {"started_speaking_at": START + 1})
    assert pairer.add("user", {"end_of_turn_delay": 0.31, "transcription_delay": 0.12}) is None

    record = pairer.add(
        "assistant", {"llm_node_ttft": 0.402, "tts_node_ttfb": 0.15, "e2e_latency": 0.8834}
    )

    assert record["kind"] == "turn" and record["turn"] == 1
    assert record["eou_delay_ms"] == 310.0
    assert record["stt_final_ms"] == 120.0
    assert record["llm_ttft_ms"] == 402.0
    assert record["tts_ttfb_ms"] == 150.0
    assert record["e2e_ms"] == 883.4


def test_missing_stages_are_none_not_zero(pairer):
    pairer.add("assistant", {})
    pairer.add("user", {"end_of_turn_delay": 0.3})
    record = pairer.add("assistant", {"e2e_latency": 0.9})
    assert record["stt_final_ms"] is None
    assert record["llm_ttft_ms"] is None
    assert record["e2e_ms"] == 900.0


def test_agent_line_without_caller_turn_is_not_a_turn(pairer):
    # e.g. "Are you still there?" after silence: nothing to time it against.
    pairer.add("assistant", {})
    assert pairer.add("assistant", {"e2e_latency": 0.5}) is None


def test_reply_is_timed_against_the_latest_caller_message(pairer):
    pairer.add("assistant", {})
    pairer.add("user", {"end_of_turn_delay": 0.9})
    pairer.add("user", {"end_of_turn_delay": 0.2})
    assert pairer.add("assistant", {"e2e_latency": 0.7})["eou_delay_ms"] == 200.0


def test_turns_are_numbered_and_each_caller_message_is_used_once(pairer):
    pairer.add("assistant", {})
    pairer.add("user", {})
    assert pairer.add("assistant", {})["turn"] == 1
    assert pairer.add("assistant", {}) is None  # the same caller message isn't reused
    pairer.add("user", {})
    assert pairer.add("assistant", {})["turn"] == 2


def test_other_roles_are_ignored(pairer):
    assert pairer.add("system", {}) is None


def test_writer_appends_one_json_line_per_record(tmp_path):
    writer = JsonlWriter(tmp_path / "metrics")
    writer.write({"kind": "turn", "e2e_ms": 812.0})
    writer.write({"kind": "turn", "e2e_ms": 790.5})
    lines = writer.path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["e2e_ms"] for line in lines] == [812.0, 790.5]
