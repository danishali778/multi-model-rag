import asyncio

import httpx
import pytest

from app.core.config import Settings
from app.domain.errors import BadRequestError, ProviderAuthenticationError
from app.llm.providers.base import (
    ChatCompletion,
    ChatProvider,
    EmbeddingProvider,
    EmbeddingResult,
    ModelConfig,
    ProviderRequestError,
)
from app.llm.router import ModelRouter


class _FakeChatProvider(ChatProvider):
    def __init__(self, provider_name: str, behavior):
        self.provider_name = provider_name
        self.behavior = behavior
        self.calls = 0

    async def complete_chat(self, messages: list[dict[str, str]], model_config: ModelConfig) -> ChatCompletion:
        self.calls += 1
        result = self.behavior(self.calls, model_config)
        if isinstance(result, Exception):
            raise result
        return result

    async def health_check(self) -> bool:
        return True


class _FakeEmbeddingProvider(EmbeddingProvider):
    provider_name = "huggingface"

    async def embed(self, texts: list[str], model_config: ModelConfig) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[0.1, 0.2, 0.3] for _ in texts],
            model_name=model_config.model_name,
            provider=self.provider_name,
            input_tokens=3,
            estimated_cost_usd=0.0,
        )

    async def health_check(self) -> bool:
        return True


def _settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        supabase_db_url="postgresql://example",
        supabase_jwks_url="https://example.supabase.co/auth/v1/.well-known/jwks.json",
        groq_api_key="groq-key",
        hf_api_token="hf-key",
        redis_url="redis://localhost:6379/0",
        **overrides,
    )


def test_router_retries_then_falls_back():
    settings = _settings(
        chat_profile_balanced_chain="groq:groq-primary|openai:gpt-4o-mini",
        chat_profile_balanced_retry_count=1,
        openai_api_key="openai-key",
    )

    def groq_behavior(call_count: int, model_config: ModelConfig):
        return ProviderRequestError(
            provider="groq",
            message="retry me",
            error_type="transient",
            retryable=True,
            status_code=503,
        )

    def openai_behavior(call_count: int, model_config: ModelConfig):
        return ChatCompletion(
            answer="fallback answer",
            model_name=model_config.model_name,
            provider="openai",
            input_tokens=10,
            output_tokens=5,
            estimated_cost_usd=0.0,
        )

    router = ModelRouter(
        settings=settings,
        chat_providers={
            "groq": _FakeChatProvider("groq", groq_behavior),
            "openai": _FakeChatProvider("openai", openai_behavior),
        },
        embedding_providers={"huggingface": _FakeEmbeddingProvider()},
    )

    result = asyncio.run(router.complete_chat([{"role": "user", "content": "hi"}], "balanced"))

    assert result.provider == "openai"
    assert result.fallback_used is True
    assert result.retry_count == 1
    assert result.attempt_count == 3


def test_router_does_not_retry_auth_errors():
    settings = _settings(chat_profile_balanced_chain="groq:groq-primary")

    def groq_behavior(call_count: int, model_config: ModelConfig):
        return ProviderRequestError(
            provider="groq",
            message="bad key",
            error_type="auth",
            retryable=False,
            status_code=401,
        )

    router = ModelRouter(
        settings=settings,
        chat_providers={"groq": _FakeChatProvider("groq", groq_behavior)},
        embedding_providers={"huggingface": _FakeEmbeddingProvider()},
    )

    with pytest.raises(ProviderAuthenticationError):
        asyncio.run(router.complete_chat([{"role": "user", "content": "hi"}], "balanced"))


def test_router_rejects_invalid_profile():
    settings = _settings()
    router = ModelRouter(
        settings=settings,
        chat_providers={"groq": _FakeChatProvider("groq", lambda *_: httpx.ConnectError("boom"))},
        embedding_providers={"huggingface": _FakeEmbeddingProvider()},
    )

    with pytest.raises(BadRequestError):
        router.chat_config("unknown", settings.profile_targets("balanced")[0])
