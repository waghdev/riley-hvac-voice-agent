"""LLM_MODEL picks where Riley's LLM runs (main.build_llm). Building a client makes no request.

Since 2026-10-27 the default is the Gemini free tier with our own key: the LiveKit Inference
credit ran out, and Inference stays one setting away for when it resets.
"""

import pytest
from livekit.agents import inference
from livekit.plugins import google

from agent import main


@pytest.fixture(autouse=True)
def dummy_keys(monkeypatch):
    # Not real keys: the clients only check that one is set.
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-secret-long-enough-for-hmac-sha256")
    monkeypatch.setattr(main, "LLM_TEMPERATURE", None)


def test_a_gemini_id_uses_the_gemini_api_with_our_key(monkeypatch):
    monkeypatch.setattr(main, "LLM_MODEL", "gemini-3.5-flash-lite")
    llm = main.build_llm()
    assert isinstance(llm, google.LLM)
    assert llm.model == "gemini-3.5-flash-lite"
    assert llm.provider == "Gemini"  # the Gemini API, not Vertex AI


def test_a_provider_slash_model_id_uses_livekit_inference(monkeypatch):
    monkeypatch.setattr(main, "LLM_MODEL", "google/gemini-3.1-flash-lite")
    llm = main.build_llm()
    assert isinstance(llm, inference.LLM)
    assert llm.model == "google/gemini-3.1-flash-lite"
