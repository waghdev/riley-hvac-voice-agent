"""Riley's conversation behavior against the real model, in text mode (no room, no audio).

Marked `llm`: these spend LiveKit Inference credit, so they run locally, not in CI:
    uv run pytest -m llm tests/behavior

Each test pins a speaking rule from CLAUDE.md section 4 or a bug found in a debugger call.
Prefer structural checks; the judge LLM is only for what can't be checked exactly.
"""

import itertools
import re

import pytest
from livekit.agents import AgentSession, ChatContext, inference, mock_tools

from agent import prompts
from agent.main import Riley, build_llm

pytestmark = pytest.mark.llm

JUDGE_MODEL = "openai/gpt-4.1-mini"  # stronger than Riley's model; used for judging only

# Exactly what was said in the debugger call where Riley re-asked for the problem (2026-10-20).
CALL_UP_TO_THE_ZIP = [
    ("user", "yeah hi, my AC is blowing warm air and it's like a hundred degrees in here"),
    ("assistant", "That sounds uncomfortable. What's your first name, please?"),
    ("user", "it's Jordan"),
    ("assistant", "Thanks, Jordan. Can I get your callback number?"),
    ("user", "six oh two, five five five, oh one four two"),
    ("assistant", "Thanks, Jordan. What's the ZIP code where you need service?"),
]

ALL_DETAILS_GIVEN = [
    *CALL_UP_TO_THE_ZIP,
    ("user", "eight five zero one six"),
    ("assistant", "Got it. A team member will call you within one business day to schedule."),
]


@pytest.fixture
async def session():
    async with build_llm() as llm, AgentSession(llm=llm) as session:
        # The real end_call needs a job context (a room), which tests don't have. Mocked for
        # the whole session, so an unexpected hang-up shows up as an assertion, not a crash.
        mock_tools(Riley, {"end_call": lambda: prompts.END_CALL_RESULT}, session=session)
        await session.start(Riley())
        yield session


@pytest.fixture
async def judge():
    async with inference.LLM(model=JUDGE_MODEL) as llm:
        yield llm


async def seed(session: AgentSession, turns: list[tuple[str, str]]) -> None:
    """Start the agent mid-call; the setup turns aren't what's under test."""
    agent = session.current_agent
    ctx: ChatContext = agent.chat_ctx.copy()
    for role, text in turns:
        ctx.add_message(role=role, content=text)
    await agent.update_chat_ctx(ctx)


def describe(events) -> list[str]:
    """One short line per event, so a failed assertion says what Riley actually did."""
    lines = []
    for e in events:
        if e.type == "function_call":
            lines.append(f"call {e.item.name}")
        elif e.type == "message":
            lines.append(f"says {e.item.text_content!r}")
        else:
            lines.append(e.type)
    return lines


async def reply_to(session: AgentSession, line: str) -> str:
    result = await session.run(user_input=line)
    return result.expect.next_event(type="message").event().item.text_content or ""


async def test_first_reply_is_short_and_asks_one_question(session):
    result = await session.run(user_input="yeah hi, my AC is blowing warm air")
    reply = result.expect.next_event().is_message(role="assistant").event().item.text_content
    result.expect.no_more_events()
    assert len(reply.split()) <= 25, reply
    assert reply.count("?") <= 1, reply


async def test_does_not_ask_again_for_a_problem_the_caller_already_described(session, judge):
    # Bug (debugger call, 2026-10-20): after the ZIP, Riley asked "can you tell me a little
    # about what's happening with your AC?" although the caller opened with exactly that.
    await seed(session, CALL_UP_TO_THE_ZIP)
    result = await session.run(user_input="eight five zero one six")
    await (
        result.expect.next_event()
        .is_message(role="assistant")
        .judge(
            judge,
            intent=(
                "Tells the caller that a team member will call back to schedule. "
                "Does not ask the caller to describe the problem or explain what is wrong. "
                "Asking whether there is anything else is fine."
            ),
        )
    )
    result.expect.no_more_events()


async def test_does_not_hang_up_before_the_caller_is_done(session):
    # Bug (behavior run, 2026-10-20): right after giving the callback promise, Riley called
    # end_call without letting the caller answer.
    await seed(session, CALL_UP_TO_THE_ZIP)
    result = await session.run(user_input="eight five zero one six")
    hang_ups = [e for e in result.events if e.type == "function_call" and e.item.name == "end_call"]
    assert not hang_ups, describe(result.events)


async def test_does_not_thank_the_caller_by_name_on_consecutive_turns(session):
    # Bug (same call): "Thanks, Jordan." on two turns in a row.
    replies = [
        await reply_to(session, line)
        for line in [
            "yeah hi, my AC is blowing warm air",
            "it's Jordan",
            "six oh two, five five five, oh one four two",
            "eight five zero one six",
        ]
    ]
    named = ["Jordan" in reply for reply in replies]
    assert not any(a and b for a, b in itertools.pairwise(named)), replies


async def test_price_question_gets_the_fixed_line_and_no_numbers(session):
    await seed(session, CALL_UP_TO_THE_ZIP)
    reply = await reply_to(session, "how much is this gonna cost me?")
    assert "exact price after diagnosing it" in reply, reply
    assert not re.search(r"\d|\$|dollar", reply, re.IGNORECASE), reply


async def test_does_not_claim_a_service_it_has_not_been_told_about(session, judge):
    # Bug (debugger call, 2026-10-20): "Yes, we do perform duct cleaning." Duct cleaning is
    # not offered (business.yaml); Riley invented the answer. M2's service_offered_gate will
    # answer this from config; until then Riley must not assert it either way.
    await seed(session, ALL_DETAILS_GIVEN)
    result = await session.run(user_input="oh, do you guys also do duct cleaning?")
    await result.expect.next_event(type="message").judge(
        judge, intent="Does not say or imply that the company offers duct cleaning."
    )


async def test_ends_the_call_once_with_one_goodbye(session, judge):
    # Bug (debugger call, 2026-10-20): end_call fired four times in parallel and Riley said
    # goodbye twice, once before the tool call and again after it.
    await seed(session, ALL_DETAILS_GIVEN)
    result = await session.run(user_input="nope, that's all. thanks, bye")
    calls = [e for e in result.events if e.type == "function_call" and e.item.name == "end_call"]
    messages = [e for e in result.events if e.type == "message"]
    assert len(calls) == 1, describe(result.events)
    assert len(messages) == 1, describe(result.events)
    await result.expect[-1].is_message(role="assistant").judge(judge, intent="Says goodbye.")
