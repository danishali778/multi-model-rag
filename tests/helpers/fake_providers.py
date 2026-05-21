from __future__ import annotations

from types import SimpleNamespace


def fake_chat_completion(*, answer: str, provider: str = "groq", model_name: str = "mock-model"):
    return SimpleNamespace(
        answer=answer,
        provider=provider,
        model_name=model_name,
        input_tokens=10,
        output_tokens=5,
        estimated_cost_usd=0.0,
    )


def fake_transcription(*, transcript: str, provider: str = "openai", model_name: str = "gpt-4o-mini-transcribe"):
    return SimpleNamespace(
        transcript=transcript,
        confidence=0.9,
        provider=provider,
        model_name=model_name,
        input_duration_ms=1200,
    )
