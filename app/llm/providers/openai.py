from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.llm.providers.base import (
    ChatCompletion,
    ChatProvider,
    EmbeddingProvider,
    EmbeddingResult,
    ModelConfig,
    ProviderRequestError,
    SpeechSynthesisResult,
    SpeechToTextConfig,
    SpeechToTextProvider,
    TextToSpeechConfig,
    TextToSpeechProvider,
    TranscriptionResult,
)
from app.llm.token_counter import count_tokens


class OpenAIChatProvider(ChatProvider):
    provider_name = "openai"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def complete_chat(self, messages: list[dict[str, str]], model_config: ModelConfig) -> ChatCompletion:
        response = await _post_openai(
            settings=self.settings,
            path="/chat/completions",
            model_config=model_config,
            json={
                "model": model_config.model_name,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": model_config.max_output_tokens,
            },
        )
        data = response.json()
        usage = data.get("usage", {})
        return ChatCompletion(
            answer=_message_content(data["choices"][0]["message"]["content"]),
            model_name=data.get("model", model_config.model_name),
            provider=self.provider_name,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            estimated_cost_usd=0.0,
        )

    async def health_check(self) -> bool:
        return bool(self.settings.openai_api_key)


class OpenAIEmbeddingProvider(EmbeddingProvider):
    provider_name = "openai"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def embed(self, texts: list[str], model_config: ModelConfig) -> EmbeddingResult:
        response = await _post_openai(
            settings=self.settings,
            path="/embeddings",
            model_config=model_config,
            json={"model": model_config.model_name, "input": texts},
        )
        data = response.json()["data"]
        vectors = [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]
        usage = response.json().get("usage", {})
        return EmbeddingResult(
            vectors=vectors,
            model_name=model_config.model_name,
            provider=self.provider_name,
            input_tokens=int(usage.get("prompt_tokens", sum(count_tokens(text) for text in texts))),
            estimated_cost_usd=0.0,
        )

    async def health_check(self) -> bool:
        return bool(self.settings.openai_api_key)


class OpenAITranscriptionProvider(SpeechToTextProvider):
    provider_name = "openai"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str,
        filename: str,
        config: SpeechToTextConfig,
    ) -> TranscriptionResult:
        response = await _post_openai_multipart(
            settings=self.settings,
            path="/audio/transcriptions",
            timeout_seconds=config.timeout_seconds,
            form_data={"model": config.model_name, "response_format": "verbose_json"},
            files={"file": (filename, audio_bytes, mime_type)},
            retry_policy=config.retry_policy,
        )
        data = response.json()
        segments = data.get("segments") if isinstance(data.get("segments"), list) else []
        duration_seconds = data.get("duration")
        duration_ms = int(float(duration_seconds) * 1000) if duration_seconds is not None else None
        return TranscriptionResult(
            transcript=str(data.get("text", "")),
            model_name=config.model_name,
            provider=self.provider_name,
            input_duration_ms=duration_ms,
            estimated_cost_usd=0.0,
            confidence=None,
            language=str(data.get("language")) if data.get("language") else None,
            segments=segments,
        )

    async def health_check(self) -> bool:
        return bool(self.settings.openai_api_key)


class OpenAITextToSpeechProvider(TextToSpeechProvider):
    provider_name = "openai"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def synthesize(
        self,
        text: str,
        config: TextToSpeechConfig,
    ) -> SpeechSynthesisResult:
        response = await _post_openai(
            settings=self.settings,
            path="/audio/speech",
            model_config=ModelConfig(
                profile="voice",
                provider=config.provider,
                model_name=config.model_name,
                timeout_seconds=config.timeout_seconds,
                max_output_tokens=1,
                retry_policy=config.retry_policy,
            ),
            json={
                "model": config.model_name,
                "input": text,
                "voice": config.voice,
                "response_format": config.audio_format,
            },
            expect_json=False,
        )
        return SpeechSynthesisResult(
            audio_bytes=response.content,
            model_name=config.model_name,
            provider=self.provider_name,
            audio_format=config.audio_format,
            output_duration_ms=None,
            estimated_cost_usd=0.0,
        )

    async def health_check(self) -> bool:
        return bool(self.settings.openai_api_key)


async def _post_openai(
    *,
    settings: Settings,
    path: str,
    model_config: ModelConfig,
    json: dict[str, Any],
    expect_json: bool = True,
) -> httpx.Response:
    if not settings.openai_api_key:
        raise ProviderRequestError(
            provider="openai",
            message="OpenAI API key is not configured.",
            error_type="auth",
            retryable=False,
        )
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=model_config.timeout_seconds) as client:
        response = await client.post(f"{str(settings.openai_base_url).rstrip('/')}{path}", headers=headers, json=json)
    if response.status_code >= 400:
        raise _request_error(response, model_config)
    if expect_json:
        response.json()
    return response


async def _post_openai_multipart(
    *,
    settings: Settings,
    path: str,
    timeout_seconds: float,
    form_data: dict[str, Any],
    files: dict[str, tuple[str, bytes, str]],
    retry_policy,
) -> httpx.Response:
    if not settings.openai_api_key:
        raise ProviderRequestError(
            provider="openai",
            message="OpenAI API key is not configured.",
            error_type="auth",
            retryable=False,
        )
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"{str(settings.openai_base_url).rstrip('/')}{path}",
            headers=headers,
            data=form_data,
            files=files,
        )
    if response.status_code >= 400:
        raise _request_error(
            response,
            ModelConfig(
                profile="voice",
                provider="openai",
                model_name=str(form_data.get("model", "openai")),
                timeout_seconds=timeout_seconds,
                max_output_tokens=1,
                retry_policy=retry_policy,
            ),
        )
    return response


def _request_error(response: httpx.Response, model_config: ModelConfig) -> ProviderRequestError:
    details = {"status_code": response.status_code, "body": response.text[:500]}
    error_type = "auth" if response.status_code in {401, 403} else "transient"
    retryable = response.status_code in model_config.retry_policy.retryable_status_codes
    if response.status_code not in model_config.retry_policy.retryable_status_codes and error_type != "auth":
        error_type = "request"
    return ProviderRequestError(
        provider="openai",
        message="OpenAI request failed.",
        error_type=error_type,
        retryable=retryable,
        status_code=response.status_code,
        details=details,
    )


def _message_content(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        return "".join(str(item.get("text", "")) for item in payload if isinstance(item, dict))
    return str(payload)
