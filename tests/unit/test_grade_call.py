"""qa/grade_call.py: reading an exported simulation run, the deterministic checks (each one both
ways), the LLM grade's parsing, and the report. No network: the model is a stand-in."""

import json

import pytest

from agent import prompts
from qa import grade_call
from qa.grade_call import CONFIG, GREETING, Call, Event, load_run, run_checks


def agent(text: str) -> Event:
    return Event("agent", text)


def caller(text: str) -> Event:
    return Event("caller", text)


def tool(name: str, **args) -> Event:
    return Event("call", name=name, data=args)


def result(name: str, decision: str, next_step: str = "continue") -> Event:
    return Event("output", name=name, data={"decision": decision, "next_step": next_step})


def call(*events: Event) -> Call:
    return Call(id="SRJ_1", label="test call", events=[agent(GREETING), *events])


def checks(c: Call) -> set[tuple[str, str]]:
    return {(f.check, f.severity) for f in run_checks(c)}


READ_BACK = [
    tool("choose_window", window_id="2026-10-22T10:00"),
    result("choose_window", "READ_BACK", "confirm_booking"),
    agent("I have 602-555-0142 and tomorrow, 10 to noon. Is that right?"),
]


# --- Reading the export -------------------------------------------------------------------------


def export(items: list[dict], *, status: str = "STATUS_COMPLETED") -> dict:
    return {
        "run": {
            "id": "SR_1",
            "scenario_group": {"name": "Core"},
            "jobs": [
                {"id": "SRJ_1", "label": "Booking", "status": status, "error": "why"},
                {"id": "SRJ_2", "label": "Never ran", "status": "STATUS_FAILED"},
            ],
        },
        "summary": {"chat_history": {"SRJ_1": {"items": items}}},
    }


def test_an_export_becomes_calls_with_messages_tool_calls_and_parsed_results():
    items = [
        {"agent_handoff": {"new_agent_id": "riley"}},
        {"message": {"role": "ASSISTANT", "content": [{"text": GREETING}]}},
        {"message": {"role": "USER", "content": [{"text": "my AC is loud"}]}},
        {"function_call": {"name": "record_issue", "arguments": '{"category": "ac_repair"}'}},
        # Tool results come as the repr of a Python dict.
        {"function_call_output": {"name": "record_issue", "output": "{'decision': 'MISSING'}"}},
        {"function_call_output": {"name": "end_call", "output": ""}},
    ]
    first, never_ran = load_run(export(items))
    assert [(e.kind, e.text or e.name) for e in first.events] == [
        ("agent", GREETING),
        ("caller", "my AC is loud"),
        ("call", "record_issue"),
        ("output", "record_issue"),
        ("output", "end_call"),
    ]
    assert first.events[2].data == {"category": "ac_repair"}
    assert first.events[3].data == {"decision": "MISSING"}
    assert (first.judge_passed, first.judge_reason) == (True, "why")
    assert never_ran.events == [] and never_ran.judge_passed is False
    assert checks(never_ran) == {("transcript", "major")}


# --- The checks -------------------------------------------------------------------------------


def test_a_clean_call_has_no_findings():
    c = call(
        caller("my AC is loud"),
        *READ_BACK,
        caller("yes"),
        tool("book_appointment"),
        result("book_appointment", "BOOKED"),
        agent("You're all set for tomorrow, 10 am-12 pm."),
        agent("Anything else I can help with?"),
    )
    assert run_checks(c) == []


def test_the_greeting_must_come_first():
    c = Call(id="x", label="x", events=[agent("Hi, what's up?")])
    assert checks(c) == {("disclosure", "critical")}


def test_a_booking_needs_a_read_back_the_caller_answered():
    no_read_back = call(tool("book_appointment"), result("book_appointment", "BOOKED"))
    same_turn = call(*READ_BACK, tool("book_appointment"), result("book_appointment", "BOOKED"))
    for c in (no_read_back, same_turn):
        assert ("booking_after_read_back", "critical") in checks(c)


def test_no_booking_steps_after_a_decision_that_ended_the_call():
    c = call(
        tool("record_service_location", zip_code="85301"),
        result("record_service_location", "OUT_OF_AREA", "end_call"),
        tool("find_windows"),
    )
    assert ("nothing_after_a_closing_gate", "critical") in checks(c)


def test_a_hazard_needs_the_exact_safety_script():
    skipped = call(caller("there's a gas smell by the furnace"), agent("Oh no. What's your ZIP?"))
    played = call(caller("I smell gas"), tool("report_safety_hazard"), agent(CONFIG.safety_script))
    assert ("safety_script", "critical") in checks(skipped)
    assert checks(played) == set()


def test_a_gas_furnace_is_not_a_hazard():
    assert checks(call(caller("my gas furnace won't heat"))) == set()


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        ("The diagnostic visit is $89, waived if you approve the repair.", True),
        ("That's eighty-nine dollars for the visit.", True),
        ("Estimates for a new system are free.", True),
        ("A compressor usually runs about $1,500.", False),
        ("Usually two hundred dollars or so.", False),
    ],
)
def test_only_the_diagnostic_fee_is_ever_quoted(line, ok):
    assert (("prices", "critical") not in checks(call(agent(line)))) is ok


def test_style_checks_on_generated_turns():
    long_turn = " ".join(["word"] * 30) + "."
    assert ("turn_length", "minor") in checks(call(agent(long_turn)))
    assert ("one_question", "minor") in checks(call(agent("What's your name? And your ZIP?")))
    assert ("plain_speech", "minor") in checks(call(agent("Options:\n- morning\n- afternoon")))
    assert ("plain_speech", "major") in checks(call(agent("As an AI, I can't do that.")))


def test_fixed_lines_are_exempt_from_style_checks():
    assert len(GREETING.split()) > grade_call.MAX_WORDS  # the reason for the exemption
    c = call(agent(CONFIG.safety_script), agent(prompts.SERVICE_UNAVAILABLE))
    assert checks(c) == set()


# --- The LLM grade and the report ---------------------------------------------------------------


def test_the_llm_grade_is_parsed_and_bad_entries_dropped():
    reply = {
        "scores": {"accuracy": 5, "clarity": 4, "empathy": 4, "efficiency": 3},
        "findings": [
            {"criterion": "efficiency", "severity": "minor", "quote": "q", "explanation": "e"},
            {"criterion": "vibes", "severity": "minor", "quote": "q", "explanation": "e"},
        ],
    }
    prompts_seen = []

    def generate(prompt: str) -> str:
        prompts_seen.append(prompt)
        return json.dumps(reply)

    rubric = {"criteria": {"accuracy": {}}, "not_findings": ["by design"]}
    scores, findings = grade_call.grade_with_llm(call(caller("hi")), rubric, generate)
    assert scores == reply["scores"]
    assert [(f.check, f.severity, f.by) for f in findings] == [("efficiency", "minor", "llm")]
    assert "Caller: hi" in prompts_seen[0] and "by design" in prompts_seen[0]


def test_checks_only_run_reports_and_fails_on_critical(tmp_path, capsys):
    bad = {"message": {"role": "ASSISTANT", "content": [{"text": "Hey there."}]}}
    path = tmp_path / "run.json"
    path.write_text(json.dumps(export([bad])), encoding="utf-8")
    out = tmp_path / "report.md"
    assert grade_call.main([str(path), "--no-llm", "--out", str(out)]) == 1
    text = out.read_text(encoding="utf-8")
    assert "# QA report: Core (SR_1)" in text
    assert "| Booking | pass | 1 | 0 | 0 |" in text
    assert "**critical** (check: disclosure)" in text
