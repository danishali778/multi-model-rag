from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from app.llm.token_counter import count_tokens


@dataclass(slots=True, frozen=True)
class RetryPolicy:
    max_retries: int
    retryable_status_codes: tuple[int, ...]


@dataclass(slots=True, frozen=True)
class ModelConfig:
    profile: str
    provider: str
    model_name: str
    timeout_seconds: float
    max_output_tokens: int
    retry_policy: RetryPolicy


@dataclass(slots=True)
class ProviderAttempt:
    provider: str
    model_name: str
    status: str
    duration_ms: int
    retryable: bool
    error_type: str | None = None
    status_code: int | None = None
    message: str | None = None


@dataclass(slots=True)
class ChatCompletion:
    answer: str
    model_name: str
    provider: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    attempts: list[ProviderAttempt] = field(default_factory=list)
    fallback_used: bool = False
    retry_count: int = 0

    @property
    def attempt_count(self) -> int:
        return len(self.attempts) or 1


@dataclass(slots=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model_name: str
    provider: str
    input_tokens: int
    estimated_cost_usd: float
    attempts: list[ProviderAttempt] = field(default_factory=list)
    fallback_used: bool = False
    retry_count: int = 0

    @property
    def attempt_count(self) -> int:
        return len(self.attempts) or 1


@dataclass(slots=True, frozen=True)
class SpeechToTextConfig:
    provider: str
    model_name: str
    timeout_seconds: float
    retry_policy: RetryPolicy


@dataclass(slots=True, frozen=True)
class TextToSpeechConfig:
    provider: str
    model_name: str
    timeout_seconds: float
    retry_policy: RetryPolicy
    voice: str
    audio_format: str


@dataclass(slots=True)
class TranscriptionResult:
    transcript: str
    model_name: str
    provider: str
    input_duration_ms: int | None = None
    estimated_cost_usd: float = 0.0
    confidence: float | None = None
    language: str | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    attempts: list[ProviderAttempt] = field(default_factory=list)
    fallback_used: bool = False
    retry_count: int = 0

    @property
    def attempt_count(self) -> int:
        return len(self.attempts) or 1


@dataclass(slots=True)
class SpeechSynthesisResult:
    audio_bytes: bytes
    model_name: str
    provider: str
    audio_format: str
    output_duration_ms: int | None = None
    estimated_cost_usd: float = 0.0
    attempts: list[ProviderAttempt] = field(default_factory=list)
    fallback_used: bool = False
    retry_count: int = 0

    @property
    def attempt_count(self) -> int:
        return len(self.attempts) or 1


@dataclass(slots=True)
class ProviderRequestError(Exception):
    provider: str
    message: str
    error_type: str
    retryable: bool
    status_code: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


class ChatProvider(ABC):
    provider_name: str

    @abstractmethod
    async def complete_chat(self, messages: list[dict[str, str]], model_config: ModelConfig) -> ChatCompletion:
        raise NotImplementedError

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        model_config: ModelConfig,
    ) -> AsyncIterator[str]:
        completion = await self.complete_chat(messages, model_config)
        yield completion.answer

    async def count_tokens(self, text: str, model_config: ModelConfig) -> int:
        return count_tokens(text)

    @abstractmethod
    async def health_check(self) -> bool:
        raise NotImplementedError


class EmbeddingProvider(ABC):
    provider_name: str

    @abstractmethod
    async def embed(self, texts: list[str], model_config: ModelConfig) -> EmbeddingResult:
        raise NotImplementedError

    async def count_tokens(self, text: str, model_config: ModelConfig) -> int:
        return count_tokens(text)

    @abstractmethod
    async def health_check(self) -> bool:
        raise NotImplementedError


class SpeechToTextProvider(ABC):
    provider_name: str

    @abstractmethod
    async def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str,
        filename: str,
        config: SpeechToTextConfig,
    ) -> TranscriptionResult:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> bool:
        raise NotImplementedError


class TextToSpeechProvider(ABC):
    provider_name: str

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        config: TextToSpeechConfig,
    ) -> SpeechSynthesisResult:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> bool:
        raise NotImplementedError
