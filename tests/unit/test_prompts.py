import pytest

from agent import prompts
from agent.config import load_business

BUSINESS = load_business()


def test_greeting_is_the_exact_script_from_business_yaml():
    assert prompts.greeting(BUSINESS) == BUSINESS["scripts"]["greeting"]


def test_instructions_are_built_from_business_yaml():
    text = prompts.build_instructions(BUSINESS)
    assert BUSINESS["agent"]["name"] in text
    assert BUSINESS["business"]["spoken_name"] in text
    assert BUSINESS["scripts"]["price_question"] in text
    assert BUSINESS["callback"]["promise"] in text
    assert f"${BUSINESS['pricing']['diagnostic_fee']}" in text


def test_every_service_category_is_listed_for_the_tools():
    text = prompts.build_instructions(BUSINESS)
    for category in [*BUSINESS["services"]["offered"], *BUSINESS["services"]["not_offered"]]:
        assert category in text


def test_instructions_use_the_spoken_name_not_the_ampersand():
    # TTS reads "&" badly; the prompt should only ever show the spoken form.
    assert "&" not in prompts.build_instructions(BUSINESS)


def test_instructions_stay_short():
    # The model re-reads the prompt every turn, so length is latency (CLAUDE.md section 4).
    # M1's limit was 300 words; M2 adds the tool workflow and the category list (~440 words).
    assert len(prompts.build_instructions(BUSINESS).split()) < 500


@pytest.mark.parametrize(
    "line", [prompts.STILL_THERE, prompts.SILENCE_GOODBYE, prompts.TIME_LIMIT_GOODBYE]
)
def test_fixed_lines_meet_the_turn_length_rule(line):
    assert len(line.split()) <= 25
