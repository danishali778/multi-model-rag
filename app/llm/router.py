from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import ProviderTarget, Settings
from app.domain.errors import BadRequestError, ProviderAuthenticationError, ProviderUnavailableError
from app.llm.providers.base import (
    ChatCompletion,
    ChatProvider,
    EmbeddingProvider,
    EmbeddingResult,
    ModelConfig,
    ProviderAttempt,
    ProviderRequestError,
    RetryPolicy,
    SpeechSynthesisResult,
    SpeechToTextProvider,
    TextToSpeechProvider,
    TextToSpeechConfig,
    SpeechToTextConfig,
    TranscriptionResult,
)


class ModelRouter:
    def __init__(
        self,
        *,
        settings: Settings,
        chat_providers: dict[str, ChatProvider],
        embedding_providers: dict[str, EmbeddingProvider],
        stt_providers: dict[str, SpeechToTextProvider] | None = None,
        tts_providers: dict[str, TextToSpeechProvider] | None = None,
        telemetry=None,
    ):
        self.settings = settings
        self.chat_providers = chat_providers
        self.embedding_providers = embedding_providers
        self.stt_providers = stt_providers or {}
        self.tts_providers = tts_providers or {}
        self.telemetry = telemetry

    def chat_config(self, profile: str, target: ProviderTarget) -> ModelConfig:
        if profile not in {"fast", "balanced", "reasoning", "local"}:
            raise BadRequestError(f"Unsupported model profile '{profile}'.")
        return self._build_config(profile, target)

    def embedding_config(self, target: ProviderTarget) -> ModelConfig:
        return self._build_config("embedding", target)

    def transcription_config(self) -> SpeechToTextConfig:
        return SpeechToTextConfig(
            provider=self.settings.voice_stt_provider,
            model_name=self.settings.openai_model_transcription,
            timeout_seconds=self.settings.voice_transcription_timeout_seconds,
            retry_policy=RetryPolicy(
                max_retries=self.settings.voice_stt_retry_count,
                retryable_status_codes=self.settings.parsed_retryable_status_codes(),
            ),
        )

    def speech_synthesis_config(self) -> TextToSpeechConfig:
        return TextToSpeechConfig(
            provider=self.settings.voice_tts_provider,
            model_name=self.settings.openai_model_tts,
            timeout_seconds=self.settings.voice_tts_timeout_seconds,
            retry_policy=RetryPolicy(
                max_retries=self.settings.voice_tts_retry_count,
                retryable_status_codes=self.settings.parsed_retryable_status_codes(),
            ),
            voice=self.settings.openai_tts_voice,
            audio_format=self.settings.voice_output_audio_format,
        )

    async def complete_chat(self, messages: list[dict[str, str]], profile: str) -> ChatCompletion:
        chain = self.settings.profile_targets(profile)
        attempts: list[ProviderAttempt] = []
        retry_count = 0
        for index, target in enumerate(chain):
            provider = self.chat_providers.get(target.provider)
            if provider is None:
                continue
            model_config = self.chat_config(profile, target)
            for attempt_index in range(model_config.retry_policy.max_retries + 1):
                started = time.perf_counter()
                try:
                    completion = await provider.complete_chat(messages, model_config)
                    completion.attempts = attempts + [
                        ProviderAttempt(
                            provider=target.provider,
                            model_name=target.model_name,
                            status="succeeded",
                            duration_ms=_duration_ms(started),
                            retryable=False,
                        )
                    ]
                    completion.fallback_used = index > 0
                    completion.retry_count = retry_count
                    if self.telemetry:
                        self.telemetry.record_model_usage(
                            operation="chat",
                            provider=target.provider,
                            profile=profile,
                            status="succeeded",
                            input_tokens=completion.input_tokens,
                            output_tokens=completion.output_tokens,
                            estimated_cost_usd=completion.estimated_cost_usd,
                        )
                    return completion
                except ProviderRequestError as exc:
                    attempts.append(
                        ProviderAttempt(
                            provider=target.provider,
                            model_name=target.model_name,
                            status="failed",
                            duration_ms=_duration_ms(started),
                            retryable=exc.retryable,
                            error_type=exc.error_type,
                            status_code=exc.status_code,
                            message=exc.message,
                        )
                    )
                    if self.telemetry:
                        self.telemetry.record_model_usage(
                            operation="chat",
                            provider=target.provider,
                            profile=profile,
                            status="failed",
                        )
                    if exc.retryable and attempt_index < model_config.retry_policy.max_retries:
                        retry_count += 1
                        continue
                    if exc.error_type == "auth" and index == len(chain) - 1:
                        raise ProviderAuthenticationError(
                            f"{target.provider} credentials are invalid or lack permissions.",
                            details=_error_details(exc, attempts, profile),
                        ) from exc
                    break
                except httpx.HTTPError as exc:
                    attempts.append(
                        ProviderAttempt(
                            provider=target.provider,
                            model_name=target.model_name,
                            status="failed",
                            duration_ms=_duration_ms(started),
                            retryable=True,
                            error_type="transport",
                            message=str(exc),
                        )
                    )
                    if self.telemetry:
                        self.telemetry.record_model_usage(
                            operation="chat",
                            provider=target.provider,
                            profile=profile,
                            status="failed",
                        )
                    if attempt_index < model_config.retry_policy.max_retries:
                        retry_count += 1
                        continue
                    break
        raise ProviderUnavailableError(
            "No chat provider could satisfy the requested profile.",
            details={"profile": profile, "attempts": [_attempt_to_dict(item) for item in attempts]},
        )

    async def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        chain = self.settings.profile_targets("embedding")
        attempts: list[ProviderAttempt] = []
        retry_count = 0
        for index, target in enumerate(chain):
            provider = self.embedding_providers.get(target.provider)
            if provider is None:
                continue
            model_config = self.embedding_config(target)
            for attempt_index in range(model_config.retry_policy.max_retries + 1):
                started = time.perf_counter()
                try:
                    result = await provider.embed(texts, model_config)
                    result.attempts = attempts + [
                        ProviderAttempt(
                            provider=target.provider,
                            model_name=target.model_name,
                            status="succeeded",
                            duration_ms=_duration_ms(started),
                            retryable=False,
                        )
                    ]
                    result.fallback_used = index > 0
                    result.retry_count = retry_count
                    if self.telemetry:
                        self.telemetry.record_model_usage(
                            operation="embedding",
                            provider=target.provider,
                            profile="embedding",
                            status="succeeded",
                            input_tokens=result.input_tokens,
                            estimated_cost_usd=result.estimated_cost_usd,
                        )
                    return result
                except ProviderRequestError as exc:
                    attempts.append(
                        ProviderAttempt(
                            provider=target.provider,
                            model_name=target.model_name,
                            status="failed",
                            duration_ms=_duration_ms(started),
                            retryable=exc.retryable,
                            error_type=exc.error_type,
                            status_code=exc.status_code,
                            message=exc.message,
                        )
                    )
                    if self.telemetry:
                        self.telemetry.record_model_usage(
                            operation="embedding",
                            provider=target.provider,
                            profile="embedding",
                            status="failed",
                        )
                    if exc.retryable and attempt_index < model_config.retry_policy.max_retries:
                        retry_count += 1
                        continue
                    if exc.error_type == "auth" and index == len(chain) - 1:
                        raise ProviderAuthenticationError(
                            f"{target.provider} embedding credentials are invalid or lack permissions.",
                            details=_error_details(exc, attempts, "embedding"),
                        ) from exc
                    break
                except httpx.HTTPError as exc:
                    attempts.append(
                        ProviderAttempt(
                            provider=target.provider,
                            model_name=target.model_name,
                            status="failed",
                            duration_ms=_duration_ms(started),
                            retryable=True,
                            error_type="transport",
                            message=str(exc),
                        )
                    )
                    if self.telemetry:
                        self.telemetry.record_model_usage(
                            operation="embedding",
                            provider=target.provider,
                            profile="embedding",
                            status="failed",
                        )
                    if attempt_index < model_config.retry_policy.max_retries:
                        retry_count += 1
                        continue
                    break
        raise ProviderUnavailableError(
            "No embedding provider could satisfy the request.",
            details={"profile": "embedding", "attempts": [_attempt_to_dict(item) for item in attempts]},
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return (await self.embed_texts(texts)).vectors

    async def transcribe_audio(
        self,
        *,
        audio_bytes: bytes,
        mime_type: str,
        filename: str,
    ) -> TranscriptionResult:
        config = self.transcription_config()
        provider = self.stt_providers.get(config.provider)
        if provider is None:
            raise ProviderUnavailableError(
                "No speech-to-text provider is configured for voice transcription.",
                details={"provider": config.provider},
            )
        started = time.perf_counter()
        try:
            result = await provider.transcribe(audio_bytes, mime_type, filename, config)
            result.attempts = [
                ProviderAttempt(
                    provider=config.provider,
                    model_name=config.model_name,
                    status="succeeded",
                    duration_ms=_duration_ms(started),
                    retryable=False,
                )
            ]
            if self.telemetry:
                self.telemetry.record_model_usage(
                    operation="transcription",
                    provider=config.provider,
                    profile="voice_stt",
                    status="succeeded",
                    estimated_cost_usd=result.estimated_cost_usd,
                )
            return result
        except ProviderRequestError as exc:
            if self.telemetry:
                self.telemetry.record_model_usage(
                    operation="transcription",
                    provider=config.provider,
                    profile="voice_stt",
                    status="failed",
                )
            if exc.error_type == "auth":
                raise ProviderAuthenticationError(
                    f"{config.provider} speech-to-text credentials are invalid or unavailable.",
                    details=_error_details(exc, [], "voice_stt"),
                ) from exc
            raise ProviderUnavailableError(
                "Speech-to-text provider is unavailable.",
                details=_error_details(exc, [], "voice_stt"),
            ) from exc
        except httpx.HTTPError as exc:
            if self.telemetry:
                self.telemetry.record_model_usage(
                    operation="transcription",
                    provider=config.provider,
                    profile="voice_stt",
                    status="failed",
                )
            raise ProviderUnavailableError(
                "Speech-to-text provider transport error.",
                details={"profile": "voice_stt", "message": str(exc)},
            ) from exc

    async def synthesize_speech(
        self,
        *,
        text: str,
    ) -> SpeechSynthesisResult:
        config = self.speech_synthesis_config()
        provider = self.tts_providers.get(config.provider)
        if provider is None:
            raise ProviderUnavailableError(
                "No text-to-speech provider is configured for voice synthesis.",
                details={"provider": config.provider},
            )
        started = time.perf_counter()
        try:
            result = await provider.synthesize(text, config)
            result.attempts = [
                ProviderAttempt(
                    provider=config.provider,
                    model_name=config.model_name,
                    status="succeeded",
                    duration_ms=_duration_ms(started),
                    retryable=False,
                )
            ]
            if self.telemetry:
                self.telemetry.record_model_usage(
                    operation="speech_synthesis",
                    provider=config.provider,
                    profile="voice_tts",
                    status="succeeded",
                    estimated_cost_usd=result.estimated_cost_usd,
                )
            return result
        except ProviderRequestError as exc:
            if self.telemetry:
                self.telemetry.record_model_usage(
                    operation="speech_synthesis",
                    provider=config.provider,
                    profile="voice_tts",
                    status="failed",
                )
            if exc.error_type == "auth":
                raise ProviderAuthenticationError(
                    f"{config.provider} text-to-speech credentials are invalid or unavailable.",
                    details=_error_details(exc, [], "voice_tts"),
                ) from exc
            raise ProviderUnavailableError(
                "Text-to-speech provider is unavailable.",
                details=_error_details(exc, [], "voice_tts"),
            ) from exc
        except httpx.HTTPError as exc:
            if self.telemetry:
                self.telemetry.record_model_usage(
                    operation="speech_synthesis",
                    provider=config.provider,
                    profile="voice_tts",
                    status="failed",
                )
            raise ProviderUnavailableError(
                "Text-to-speech provider transport error.",
                details={"profile": "voice_tts", "message": str(exc)},
            ) from exc

    async def health_check(self) -> bool:
        checks = []
        for provider_name in {target.provider for target in self.settings.profile_targets("balanced")}:
            provider = self.chat_providers.get(provider_name)
            if provider is not None:
                checks.append(await provider.health_check())
        for provider_name in {target.provider for target in self.settings.profile_targets("embedding")}:
            provider = self.embedding_providers.get(provider_name)
            if provider is not None:
                checks.append(await provider.health_check())
        if self._voice_required_for_healthcheck() and self.stt_providers:
            provider = self.stt_providers.get(self.settings.voice_stt_provider)
            if provider is not None:
                checks.append(await provider.health_check())
        if self._voice_required_for_healthcheck() and self.tts_providers:
            provider = self.tts_providers.get(self.settings.voice_tts_provider)
            if provider is not None:
                checks.append(await provider.health_check())
        return all(checks) if checks else False

    def _voice_required_for_healthcheck(self) -> bool:
        return self.settings.environment.lower() != "development"

    def _build_config(self, profile: str, target: ProviderTarget) -> ModelConfig:
        return ModelConfig(
            profile=profile,
            provider=target.provider,
            model_name=target.model_name,
            timeout_seconds=self.settings.profile_timeout_seconds(profile),
            max_output_tokens=self.settings.profile_max_output_tokens(profile),
            retry_policy=RetryPolicy(
                max_retries=self.settings.profile_retry_count(profile),
                retryable_status_codes=self.settings.parsed_retryable_status_codes(),
            ),
        )


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _attempt_to_dict(attempt: ProviderAttempt) -> dict[str, Any]:
    return {
        "provider": attempt.provider,
        "model_name": attempt.model_name,
        "status": attempt.status,
        "duration_ms": attempt.duration_ms,
        "retryable": attempt.retryable,
        "error_type": attempt.error_type,
        "status_code": attempt.status_code,
        "message": attempt.message,
    }


def _error_details(exc: ProviderRequestError, attempts: list[ProviderAttempt], profile: str) -> dict[str, Any]:
    details = dict(exc.details)
    details["profile"] = profile
    details["attempts"] = [_attempt_to_dict(item) for item in attempts]
    return details
