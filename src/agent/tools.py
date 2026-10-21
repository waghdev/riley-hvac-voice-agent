"""Riley's LLM tools: thin LiveKit wrappers around intake.py (CLAUDE.md section 6).

The LLM extracts facts and calls these; intake.py and gates.py decide. Each tool runs the pure
logic against this call's CallState (the session's userdata), then:
- enforces safety in code: on a hazard it plays the exact safety script and hangs up, with no LLM
  reply to paraphrase it;
- shortens endpointing when Riley's next question has a short answer (name, number, ZIP);
- returns the gate's decision, `say` and `next_step` for the LLM to follow.
"""

from typing import Any, Literal

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError, Toolset

from agent import intake, prompts
from agent.config import load_config
from agent.gates import GateResult
from agent.state import CallState

CONFIG = load_config()

# Enums in the tool schemas, built from business.yaml, so the LLM can't invent an id.
Category = Literal[tuple(CONFIG.offered) + tuple(CONFIG.not_offered)]  # type: ignore[valid-type]
SafetySignal = Literal[tuple(sorted(CONFIG.safety_signals))]  # type: ignore[valid-type]
VulnerableOccupant = Literal[tuple(sorted(CONFIG.vulnerable_occupants))]  # type: ignore[valid-type]
CallbackReason = Literal[tuple(sorted(CONFIG.callback_reasons))]  # type: ignore[valid-type]

# Endpointing: how long the turn detector may wait when it isn't sure the caller has finished.
# After a name or digits it often isn't, so it waited the full 2.5 s on 5 of 14 cloud turns.
# While Riley is collecting one of those, the wait drops to 1 s (Dev's decision, 2026-10-21).
DEFAULT_MAX_DELAY = 2.5  # the audio turn detector's documented default
SHORT_MAX_DELAY = 1.0
SHORT_ANSWER_FIELDS = frozenset({"first_name", "callback_number", "zip_code"})


def endpointing_for(state: CallState) -> dict[str, float]:
    short = state.expecting in SHORT_ANSWER_FIELDS
    return {"max_delay": SHORT_MAX_DELAY if short else DEFAULT_MAX_DELAY}


def _formatted_number(digits: str) -> str:
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def _acknowledge(context: RunContext[CallState]) -> str | None:
    """Say "Got it." now, once per caller turn, while the LLM writes the follow-up.

    A tool turn needs two LLM round trips (one to call the tool, one to reply) before any audio,
    and the model won't put text before its tool call. LiveKit's documented hold-message pattern:
    say() inside the tool, not awaited, plays while the rest of the turn is generated.
    """
    state = context.userdata
    if state.acknowledged:
        return None
    state.acknowledged = True
    line = prompts.ACKNOWLEDGEMENTS[state.acks_said % len(prompts.ACKNOWLEDGEMENTS)]
    state.acks_said += 1
    context.session.say(line)
    return line


def _respond(context: RunContext[CallState], result: GateResult) -> dict[str, Any] | None:
    state, session = context.userdata, context.session
    if result.next_step == "say_exact_then_end_call":
        # Safety is enforced in code: the exact script, uninterruptible, then hang up. Returning
        # None means no LLM reply, so nothing can soften or reword it.
        handle = session.say(CONFIG.safety_script, allow_interruptions=False)
        handle.add_done_callback(lambda _: session.shutdown())
        return None
    said = _acknowledge(context)
    session.update_options(endpointing_opts=endpointing_for(state))
    out: dict[str, Any] = result.to_tool_output()
    if said:
        # Right next to the reply being written, so the model doesn't open with another "Thanks."
        out["you_just_said"] = f"{said} (already spoken; don't acknowledge again)"
    if result.next_step == "end_call":
        # A gate ended the call, so code hangs up, not the LLM: once Riley's reply to this result
        # has played, the session closes. Leaving it to end_call gave two goodbyes, or none and
        # an open line (behavior tests, 2026-10-21). LiveKit's EndCallTool uses the same hook.
        context.speech_handle.add_done_callback(lambda _: session.shutdown())
        out["say"] = (
            f"{result.say} Then say a short goodbye. The call ends by itself after your reply; "
            "don't call end_call."
        ).strip()
    if state.callback_number:
        out["callback_number_on_file"] = _formatted_number(state.callback_number)  # for read-back
    return out


async def no_second_goodbye(ev: Toolset.ToolCompletedEvent) -> None:
    """EndCallTool hook: if a gate already ended the call, Riley has said goodbye; don't cue
    another. Returning no output means no reply, and the call ends after the current speech."""
    if ev.ctx.userdata.outcome is not None:
        ev.output = None


def _run(context: RunContext[CallState], logic, **kwargs) -> dict[str, Any] | None:
    try:
        result = logic(context.userdata, CONFIG, **kwargs)
    except ValueError as e:  # an id the schema should have prevented; let the LLM correct it
        raise ToolError(str(e)) from e
    return _respond(context, result)


@function_tool
async def record_issue(
    context: RunContext[CallState],
    category: Category,
    symptoms: str,
    not_working: bool,
    vulnerable_occupant: VulnerableOccupant | None = None,
    indoor_temp_f: int | None = None,
    safety_signals: list[SafetySignal] | None = None,
) -> dict[str, Any] | None:
    """Record what the caller needs, as soon as they describe the problem. Call again if it changes.

    Args:
        category: The service category that fits, from the list in your instructions.
        symptoms: The problem in a few words, in the caller's terms.
        not_working: True only if the system gives no cooling or no heat at all.
        vulnerable_occupant: Only if the caller says someone at home is 65 or older, an infant,
            or has a medical condition made worse by heat.
        indoor_temp_f: The indoor temperature in Fahrenheit, only if the caller mentions it.
        safety_signals: Any hazard the caller mentions in the same breath.
    """
    return _run(
        context,
        intake.record_issue,
        category=category,
        symptoms=symptoms,
        not_working=not_working,
        vulnerable_occupant=vulnerable_occupant,
        indoor_temp_f=indoor_temp_f,
        safety_signals=safety_signals or [],
    )


@function_tool
async def record_caller_details(
    context: RunContext[CallState],
    first_name: str | None = None,
    callback_number: str | None = None,
) -> dict[str, Any] | None:
    """Record the caller's first name and/or callback number as soon as they say them.

    Pass the number exactly as you heard it, digits or words. If the caller corrects a detail,
    call this again with the corrected value. Leave out anything they haven't said; never guess
    or pass a placeholder such as "unknown".

    Args:
        first_name: The caller's first name.
        callback_number: The best number to call them back on, as heard.
    """
    return _run(
        context,
        intake.record_caller_details,
        first_name=first_name,
        callback_number=callback_number,
    )


@function_tool
async def record_service_location(
    context: RunContext[CallState], zip_code: str
) -> dict[str, Any] | None:
    """Record the ZIP code where service is needed, as soon as the caller says it.

    Args:
        zip_code: The ZIP code exactly as you heard it, digits or words.
    """
    return _run(context, intake.record_service_location, zip_code=zip_code)


@function_tool
async def report_safety_hazard(
    context: RunContext[CallState], signal: SafetySignal
) -> dict[str, Any] | None:
    """Call immediately, at any point in the call, if the caller mentions a smell of gas, a carbon
    monoxide alarm going off, a burning smell from the unit, sparks, or smoke.

    Don't say anything yourself first; the safety message plays automatically and ends the call.

    Args:
        signal: Which hazard the caller described.
    """
    return _run(context, intake.report_safety_hazard, signal=signal)


@function_tool
async def request_callback(
    context: RunContext[CallState],
    reason: CallbackReason,
    first_name: str | None = None,
    callback_number: str | None = None,
) -> dict[str, Any] | None:
    """Arrange a callback from the team: the caller wants a person, has a billing question, asks
    about an existing appointment, has a complaint, or needs something you can't handle.

    Args:
        reason: Why they need a callback.
        first_name: The caller's first name, only if they've said it.
        callback_number: Their callback number as heard, only if they've said it.
    """
    return _run(
        context,
        intake.request_callback,
        reason=reason,
        first_name=first_name,
        callback_number=callback_number,
    )


ALL_TOOLS = [
    record_issue,
    record_caller_details,
    record_service_location,
    report_safety_hazard,
    request_callback,
]
