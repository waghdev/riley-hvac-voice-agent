"""Grade Riley's calls: deterministic checks first, then an LLM rubric (qa/rubric.yaml).

Input is an exported agent simulation run, so every caller is fictional:
    lk agent simulate export <run-id> > run.json
    uv run python -m qa.grade_call run.json --out qa/reports/<name>.md
    uv run python -m qa.grade_call run.json --no-llm   # checks only: no key, no network

The checks are code and certain: a booking without a confirmed read-back, a price that isn't
the diagnostic fee, a skipped safety script. The rubric (accuracy, clarity, empathy,
efficiency) needs judgement, so a model grades it, with a severity for each finding. The model
is Gemini on Google AI Studio's free tier with GOOGLE_API_KEY (offline, so its slowness doesn't
matter; the free tier may use prompts for training, which is why only simulations go in).

Exit code 1 if any call has a critical finding.
"""

import argparse
import ast
import json
import os
import re
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from agent import prompts
from agent.config import REPO_ROOT, load_business, load_config

RUBRIC_PATH = Path(__file__).with_name("rubric.yaml")
SEVERITIES = ("critical", "major", "minor")
CRITERIA = ("accuracy", "clarity", "empathy", "efficiency")
DEFAULT_MODEL = "gemini-3.5-flash-lite"
MAX_WORDS = 25  # CLAUDE.md section 4: turns of about 25 words at most

BUSINESS = load_business()
CONFIG = load_config()
GREETING = prompts.greeting(BUSINESS)
PRICING = BUSINESS["pricing"]
ALLOWED_PRICES = {PRICING["diagnostic_fee"], PRICING["new_system_estimate_fee"]}
# Said word for word by code, so the length and style checks don't apply to them.
FIXED_LINES = {
    GREETING,
    CONFIG.safety_script,
    prompts.SERVICE_UNAVAILABLE,
    prompts.TIME_LIMIT_GOODBYE,
    prompts.SILENCE_GOODBYE,
    prompts.STILL_THERE,
    prompts.CHECKING_SCHEDULE,
    *prompts.ACKNOWLEDGEMENTS,
}
BOOKED_PREFIX = prompts.BOOKED.split("{")[0]  # "You're all set for "

# What a caller says when there's a hazard (business.yaml safety.signals). Phrases, not single
# words: "gas" alone would match "my gas furnace".
SAFETY_WORDS = re.compile(
    r"\b(smell(s|ing)? (of )?gas|gas (smell|leak)|carbon monoxide|co (alarm|detector)"
    r"|burning smell|smell(s|ing)? (like )?(something )?burning|sparks?|sparking|smoke|smoking)\b",
    re.I,
)
MONEY = re.compile(r"\$\s?(\d[\d,]*)(?:\.\d\d)?|\b(\d[\d,]*)\s*(?:dollars|bucks)\b", re.I)
SPELLED_PRICES = {"eighty-nine": 89, "eighty nine": 89, "zero": 0}
SPELLED_MONEY = re.compile(r"\b([a-z]+(?:[- ][a-z]+)?) dollars\b", re.I)
AI_TALK = re.compile(r"\b(as an ai|an ai model|language model|i'?m an ai|i am an ai)\b", re.I)
LIST_OR_MARKDOWN = re.compile(r"(^\s*([-*•]|\d+\.)\s)|\*\*|^#", re.M)
# Tool results that end the call (the gate hangs up after Riley's reply).
CLOSING_STEPS = {"end_call", "say_exact_then_end_call"}
BOOKING_DECISIONS = {"OFFER_WINDOWS", "READ_BACK", "BOOKED"}
BOOKING_TOOLS = {"find_windows", "choose_window", "book_appointment"}


# --- A call, read from the export -------------------------------------------------------------


@dataclass
class Event:
    kind: str  # "agent", "caller", "call" (a tool call) or "output" (its result)
    text: str = ""
    name: str = ""  # tool name, for calls and outputs
    data: dict[str, Any] = field(default_factory=dict)  # call arguments or parsed result


@dataclass
class Call:
    id: str
    label: str
    events: list[Event]
    judge_passed: bool | None = None
    judge_reason: str = ""

    def agent_lines(self) -> list[tuple[int, str]]:
        return [(i, e.text) for i, e in enumerate(self.events) if e.kind == "agent"]


def _parse_output(raw: str) -> dict[str, Any]:
    """Tool results arrive as the Python repr of a dict ("{'decision': ...}"), or plain text."""
    for parse in (ast.literal_eval, json.loads):
        try:
            value = parse(raw)
        except (ValueError, SyntaxError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    return {"text": raw} if raw else {}


def _events(items: Iterable[dict[str, Any]]) -> list[Event]:
    events = []
    for item in items:
        if "message" in item:
            m = item["message"]
            text = " ".join(c.get("text", "") for c in m.get("content", [])).strip()
            role = "agent" if m.get("role") == "ASSISTANT" else "caller"
            if text:
                events.append(Event(role, text))
        elif "function_call" in item:
            f = item["function_call"]
            try:
                args = json.loads(f.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"raw": f.get("arguments")}
            events.append(Event("call", name=f["name"], data=args))
        elif "function_call_output" in item:
            f = item["function_call_output"]
            events.append(Event("output", name=f["name"], data=_parse_output(f.get("output", ""))))
    return events


def load_run(export: dict[str, Any]) -> list[Call]:
    """The calls in an `lk agent simulate export` file, in run order."""
    history = export.get("summary", {}).get("chat_history", {})
    calls = []
    for job in export["run"]["jobs"]:
        items = history.get(job["id"], {}).get("items", [])
        calls.append(
            Call(
                id=job["id"],
                label=job.get("label", job["id"]),
                events=_events(items),
                judge_passed=job.get("status") == "STATUS_COMPLETED",
                judge_reason=job.get("error", ""),
            )
        )
    return calls


# --- Deterministic checks -------------------------------------------------------------------


@dataclass
class Finding:
    check: str  # a deterministic check, or a rubric criterion
    severity: str
    detail: str
    by: str = "check"  # "check" (code) or "llm"


def check_disclosure(call: Call) -> list[Finding]:
    lines = call.agent_lines()
    if lines and lines[0][1] == GREETING:
        return []
    first = lines[0][1] if lines else "(nothing)"
    return [Finding("disclosure", "critical", f"first line wasn't the greeting: {first!r}")]


def _decision(e: Event) -> str | None:
    return e.data.get("decision") if e.kind == "output" else None


def check_booking_after_read_back(call: Call) -> list[Finding]:
    findings = []
    for i, e in enumerate(call.events):
        if _decision(e) != "BOOKED":
            continue
        # The book_appointment call that produced it, and the last read-back before that.
        book = max((j for j in range(i) if call.events[j].kind == "call"), default=i)
        read_backs = [j for j in range(book) if _decision(call.events[j]) == "READ_BACK"]
        answered = read_backs and any(
            call.events[j].kind == "caller" for j in range(read_backs[-1], book)
        )
        if not answered:
            detail = "booked without a confirmed read-back"
            findings.append(Finding("booking_after_read_back", "critical", detail))
    return findings


def check_nothing_after_closing(call: Call) -> list[Finding]:
    closing = next(
        (
            i
            for i, e in enumerate(call.events)
            if (e.kind == "output" and e.data.get("next_step") in CLOSING_STEPS)
            or (e.kind == "call" and e.name == "report_safety_hazard")
        ),
        None,
    )
    if closing is None:
        return []
    after = call.events[closing + 1 :]
    if any(
        (e.kind == "output" and e.data.get("decision") in BOOKING_DECISIONS)
        or (e.kind == "call" and e.name in BOOKING_TOOLS)
        for e in after
    ):
        return [
            Finding(
                "nothing_after_a_closing_gate",
                "critical",
                "kept booking after a decision that ended the call",
            )
        ]
    return []


def check_safety_script(call: Call) -> list[Finding]:
    for i, e in enumerate(call.events):
        if e.kind == "caller" and (m := SAFETY_WORDS.search(e.text)):
            said = any(
                later.kind == "agent" and later.text == CONFIG.safety_script
                for later in call.events[i:]
            )
            if not said:
                return [
                    Finding(
                        "safety_script",
                        "critical",
                        f"caller said {m.group(0)!r}; the safety script never played "
                        "(keyword match: check the transcript if it was negated)",
                    )
                ]
            return []
    return []


def _amounts(text: str) -> set[int]:
    found = {int((a or b).replace(",", "")) for a, b in MONEY.findall(text)}
    for words in SPELLED_MONEY.findall(text):
        found.add(SPELLED_PRICES.get(words.lower(), -1))  # any other spelled amount is unknown
    return found


def check_prices(call: Call) -> list[Finding]:
    findings = []
    for _, text in call.agent_lines():
        if bad := sorted(_amounts(text) - ALLOWED_PRICES):
            shown = ", ".join("an unparsed amount" if a < 0 else f"${a}" for a in bad)
            findings.append(Finding("prices", "critical", f"stated {shown}: {text!r}"))
    return findings


def _generated(text: str) -> bool:
    return text not in FIXED_LINES and not text.startswith(BOOKED_PREFIX)


def check_style(call: Call) -> list[Finding]:
    findings = []
    for _, text in call.agent_lines():
        if not _generated(text):
            continue
        if (words := len(text.split())) > MAX_WORDS:
            findings.append(Finding("turn_length", "minor", f"{words} words: {text!r}"))
        if text.count("?") > 1:
            findings.append(Finding("one_question", "minor", f"two questions: {text!r}"))
        if LIST_OR_MARKDOWN.search(text):
            findings.append(Finding("plain_speech", "minor", f"list or markdown: {text!r}"))
        if AI_TALK.search(text):
            findings.append(Finding("plain_speech", "major", f"AI talk: {text!r}"))
    return findings


CHECKS: tuple[Callable[[Call], list[Finding]], ...] = (
    check_disclosure,
    check_booking_after_read_back,
    check_nothing_after_closing,
    check_safety_script,
    check_prices,
    check_style,
)


def run_checks(call: Call) -> list[Finding]:
    if not call.events:
        return [Finding("transcript", "major", "no transcript in the export (call didn't run)")]
    return [f for check in CHECKS for f in check(call)]


# --- The LLM rubric ---------------------------------------------------------------------------

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        # First, so the model reasons through the call before it scores (with scores first,
        # every model tried gave 5/5/5/5 to a call that never confirmed its booking).
        "analysis": {"type": "string"},
        "scores": {
            "type": "object",
            "properties": {c: {"type": "integer", "minimum": 1, "maximum": 5} for c in CRITERIA},
            "required": list(CRITERIA),
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {"type": "string", "enum": list(CRITERIA)},
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "quote": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["criterion", "severity", "quote", "explanation"],
            },
        },
    },
    "required": ["analysis", "scores", "findings"],
}


def render(call: Call) -> str:
    """The call as the grader reads it: who said what, and what each tool decided."""
    lines = []
    for e in call.events:
        if e.kind == "agent":
            lines.append(f"Riley: {e.text}")
        elif e.kind == "caller":
            lines.append(f"Caller: {e.text}")
        elif e.kind == "call":
            lines.append(f"  [Riley calls {e.name}({json.dumps(e.data)})]")
        elif e.data.get("decision"):
            lines.append(f"  [{e.name} decided {e.data['decision']}: {e.data.get('say', '')}]")
    return "\n".join(lines)


def grading_prompt(call: Call, rubric: dict[str, Any]) -> str:
    facts = {
        "business": BUSINESS["business"]["name"],
        "service_area": f"{CONFIG.service_area} ZIP codes {sorted(CONFIG.zip_codes)}",
        "services_offered": list(CONFIG.offered.values()),
        "not_offered": list(CONFIG.not_offered.values()),
        "prices": BUSINESS["pricing"],
        "callback_promise": CONFIG.callback_promise,
    }
    return (
        "You are the QA lead at a call center that answers phones for home-service companies, "
        "reviewing a call answered by Riley, a voice assistant for a fictional HVAC company. "
        "Your standard is a skilled human receptionist. Grade only what Riley said and did, "
        "against the rubric; a caller hears speech, so judge it as speech.\n"
        "In `analysis`, go through the call turn by turn: what the caller needed at that point, "
        "what Riley said, and anything a caller would notice (a missed or wrong detail, an "
        "unanswered question, an ending where the caller isn't sure what happened). Then list "
        "every problem the analysis noted as a finding, quoting Riley's exact words, and score "
        "each criterion to match its findings: 5 none, 4 only minor, 3 a major, 2 or 1 a "
        "critical. Don't invent problems: a clean call gets 5s and no findings.\n\n"
        f"Rubric:\n{yaml.safe_dump({'criteria': rubric['criteria']}, sort_keys=False)}\n"
        "Not findings (how the system is built):\n- " + "\n- ".join(rubric["not_findings"]) + "\n\n"
        f"Business facts:\n{json.dumps(facts, indent=1)}\n\n"
        f"The call ({call.label}):\n{render(call)}\n"
    )


def gemini(model: str) -> Callable[[str], str]:
    """A function prompt -> JSON text, on the Gemini free tier, with retries for rate limits."""
    from google import genai  # imported here: --no-llm runs need no key and no network
    from google.genai import errors, types

    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    config = types.GenerateContentConfig(
        response_mime_type="application/json", response_json_schema=GRADE_SCHEMA, temperature=0
    )

    def generate(prompt: str) -> str:
        for attempt in range(4):
            try:
                response = client.models.generate_content(
                    model=model, contents=prompt, config=config
                )
                return response.text or "{}"
            except errors.APIError as e:
                if e.code not in (429, 500, 503) or attempt == 3:
                    raise
                time.sleep(15 * (attempt + 1))  # free-tier limits are per minute
        raise AssertionError("unreachable")

    return generate


def grade_with_llm(
    call: Call, rubric: dict[str, Any], generate: Callable[[str], str]
) -> tuple[dict[str, int], list[Finding]]:
    result = json.loads(generate(grading_prompt(call, rubric)))
    scores = {c: int(result["scores"][c]) for c in CRITERIA}
    findings = [
        Finding(f["criterion"], f["severity"], f"{f['explanation']} ({f['quote']!r})", by="llm")
        for f in result.get("findings", [])
        if f.get("severity") in SEVERITIES and f.get("criterion") in CRITERIA
    ]
    return scores, findings


# --- Report -----------------------------------------------------------------------------------


@dataclass
class Graded:
    call: Call
    findings: list[Finding]
    scores: dict[str, int] | None = None

    def count(self, severity: str) -> int:
        return sum(f.severity == severity for f in self.findings)


def report(run_id: str, name: str, graded: list[Graded]) -> str:
    out = [f"# QA report: {name} ({run_id})\n"]
    total = {s: sum(g.count(s) for g in graded) for s in SEVERITIES}
    out.append(
        f"{len(graded)} calls; findings: {total['critical']} critical, {total['major']} major, "
        f"{total['minor']} minor.\n"
    )
    columns = ["Call", "Judge", *(s.title() for s in SEVERITIES), *(c.title() for c in CRITERIA)]
    out += ["| " + " | ".join(columns) + " |", "|" + " --- |" * len(columns)]
    for g in graded:
        scores = [str(g.scores[c]) if g.scores else "-" for c in CRITERIA]
        judge = {True: "pass", False: "fail", None: "-"}[g.call.judge_passed]
        cells = [g.call.label, judge, *(str(g.count(s)) for s in SEVERITIES), *scores]
        out.append("| " + " | ".join(cells) + " |")
    for g in graded:
        out.append(f"\n## {g.call.label}\n")
        if not g.findings:
            out.append("No findings.")
        for f in sorted(g.findings, key=lambda f: SEVERITIES.index(f.severity)):
            out.append(f"- **{f.severity}** ({f.by}: {f.check}) {f.detail}")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path, help="lk agent simulate export <run-id> > this file")
    parser.add_argument("--no-llm", action="store_true", help="deterministic checks only")
    parser.add_argument(
        "--model", help=f"Gemini model (default: QA_MODEL, else GEMINI_MODEL, else {DEFAULT_MODEL})"
    )
    parser.add_argument("--out", type=Path, help="write the Markdown report here too")
    args = parser.parse_args(argv)

    load_dotenv(REPO_ROOT / ".env")
    export = json.loads(args.export.read_text(encoding="utf-8"))
    rubric = yaml.safe_load(RUBRIC_PATH.read_text(encoding="utf-8"))
    model = args.model or os.getenv("QA_MODEL") or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
    generate = None if args.no_llm else gemini(model)

    graded = []
    for call in load_run(export):
        g = Graded(call, run_checks(call))
        if generate is not None and call.events:
            g.scores, llm_findings = grade_with_llm(call, rubric, generate)
            g.findings += llm_findings
        graded.append(g)

    run = export["run"]
    text = report(run["id"], run.get("scenario_group", {}).get("name", ""), graded)
    if generate is not None:
        text += f"\nRubric graded by `{model}` (Gemini free tier).\n"
    sys.stdout.buffer.write(text.encode("utf-8"))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 1 if any(g.count("critical") for g in graded) else 0


if __name__ == "__main__":
    sys.exit(main())
