"""Where Riley's LLM runs (main.build_llm), and what happens when the first choice fails.

LiveKit Inference first, on the Build plan's monthly credit; when it refuses (the credit runs out
mid-month), the Gemini free tier with our own key carries the call on (Dev's decision,
2026-10-27). Building a client makes no request; the fallback tests use stand-in models.
"""

import pytest
from livekit.agents import APIConnectionError, APIConnectOptions, APIStatusError, inference, llm
from livekit.agents.llm import ChatChunk, ChatContext, ChoiceDelta
from livekit.plugins import google

from agent import main


@pytest.fixture(autouse=True)
def dummy_keys(monkeypatch):
    # Not real keys: the clients only check that one is set.
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-secret-long-enough-for-hmac-sha256")
    monkeypatch.setattr(main, "LLM_TEMPERATURE", None)


def test_production_is_inference_first_then_the_gemini_free_tier(monkeypatch):
    monkeypatch.setattr(main, "LLM_MODEL", "google/gemini-3.1-flash-lite")
    monkeypatch.setattr(main, "LLM_FALLBACK_MODEL", "gemini-3.5-flash-lite")
    adapter = main.build_llm()
    assert isinstance(adapter, llm.FallbackAdapter)
    primary, fallback = adapter._llm_instances
    assert isinstance(primary, inference.LLM) and primary.model == "google/gemini-3.1-flash-lite"
    assert isinstance(fallback, google.LLM) and fallback.model == "gemini-3.5-flash-lite"
    assert fallback.provider == "Gemini"  # the Gemini API with our key, not Vertex AI


def test_without_a_fallback_model_only_the_first_is_used(monkeypatch):
    # Local testing: LLM_MODEL is a free-tier model and LLM_FALLBACK_MODEL is empty, so tests
    # never spend the Inference credit that callers need.
    monkeypatch.setattr(main, "LLM_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setattr(main, "LLM_FALLBACK_MODEL", "")
    assert isinstance(main.build_llm(), google.LLM)
    monkeypatch.setattr(main, "LLM_MODEL", "google/gemini-3.1-flash-lite")
    assert isinstance(main.build_llm(), inference.LLM)


# --- The fallback itself, with stand-in models --------------------------------------------------


class StandIn(llm.LLM):
    """Answers with `reply`, or refuses the way the Inference gateway does once the credit is
    gone (`reply` None)."""

    def __init__(self, name: str, reply: str | None) -> None:
        super().__init__()
        self._name, self.reply = name, reply
        self.timeouts: list[float] = []  # each request's timeout, as the adapter set it

    @property
    def model(self) -> str:
        return self._name

    def chat(self, *, chat_ctx, tools=None, conn_options=None, **kwargs) -> llm.LLMStream:
        self.timeouts.append(conn_options.timeout)
        return _StandInStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class _StandInStream(llm.LLMStream):
    async def _run(self) -> None:
        reply = self._llm.reply  # type: ignore[attr-defined]
        if reply is None:
            raise APIStatusError("inference_quota_exceeded", status_code=429, retryable=False)
        delta = ChoiceDelta(role="assistant", content=reply)
        self._event_ch.send_nowait(ChatChunk(id="1", delta=delta))


async def reply_from(adapter: llm.LLM) -> str:
    # No retries of the whole chain, so a failing test fails at once.
    stream = adapter.chat(chat_ctx=ChatContext.empty(), conn_options=APIConnectOptions(max_retry=0))
    async with stream:
        return "".join([c.delta.content or "" async for c in stream if c.delta])


async def test_when_inference_refuses_the_free_tier_answers_and_the_call_goes_on():
    adapter = main.with_fallback(StandIn("inference", None), StandIn("free tier", "Got it."))
    errors: list = []
    adapter.on("error", errors.append)  # what the session listens to (main.close_on_fatal_error)
    assert await reply_from(adapter) == "Got it."
    assert await reply_from(adapter) == "Got it."  # and the next turn too
    # The SDK keeps a covered failure to the model that failed (livekit-agents 1.8.8; the
    # fallback docs say the session hears of it). If it reached the session, Riley would hang
    # up on a call the free tier was carrying.
    assert errors == []


async def test_each_model_gets_a_timeout_gemini_accepts():
    # Bug (text simulation on the deployed agent, 2026-10-27): every fallback request came back
    # 400 "Manually set deadline 5s is too short. Minimum allowed deadline is 10s." The adapter
    # gives each model its attempt timeout (5 s by default), and the Gemini plugin sends it to
    # Google as the request deadline. So the fallback never answered.
    free_tier = StandIn("free tier", "Got it.")
    await reply_from(main.with_fallback(StandIn("inference", None), free_tier))
    assert free_tier.timeouts and min(free_tier.timeouts) >= 10.0


async def test_when_both_fail_the_session_hears_it_and_riley_hangs_up():
    adapter = main.with_fallback(StandIn("inference", None), StandIn("free tier", None))
    errors: list = []
    adapter.on("error", errors.append)
    with pytest.raises(APIConnectionError, match="all LLMs failed"):
        await reply_from(adapter)
    assert [e.recoverable for e in errors] == [False]  # close_on_fatal_error acts on this
