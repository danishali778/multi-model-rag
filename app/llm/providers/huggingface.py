from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.llm.providers.base import EmbeddingProvider, EmbeddingResult, ModelConfig, ProviderRequestError
from app.llm.token_counter import count_tokens


class HuggingFaceEmbeddingProvider(EmbeddingProvider):
    provider_name = "huggingface"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def embed(self, texts: list[str], model_config: ModelConfig) -> EmbeddingResult:
        if not self.settings.hf_api_token:
            raise ProviderRequestError(
                provider=self.provider_name,
                message="Hugging Face API token is not configured.",
                error_type="auth",
                retryable=False,
            )
        headers = {"Authorization": f"Bearer {self.settings.hf_api_token}"}
        endpoint = _endpoint_url(str(self.settings.hf_base_url), model_config.model_name)
        async with httpx.AsyncClient(timeout=model_config.timeout_seconds) as client:
            vectors: list[list[float]] = []
            for text in texts:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json={"inputs": text, "options": {"wait_for_model": True}},
                )
                if response.status_code >= 400:
                    raise _request_error(self.provider_name, response, model_config)
                vectors.append(_normalize_embedding(response.json()))
        return EmbeddingResult(
            vectors=vectors,
            model_name=model_config.model_name,
            provider=self.provider_name,
            input_tokens=sum(count_tokens(text) for text in texts),
            estimated_cost_usd=0.0,
        )

    async def health_check(self) -> bool:
        return bool(self.settings.hf_api_token)


def _normalize_embedding(payload: Any) -> list[float]:
    if payload and isinstance(payload[0], (int, float)):
        return [float(value) for value in payload]
    if payload and isinstance(payload[0], list) and payload[0] and isinstance(payload[0][0], (int, float)):
        rows = [[float(value) for value in row] for row in payload]
        width = len(rows[0])
        return [sum(row[index] for row in rows) / len(rows) for index in range(width)]
    raise ProviderRequestError(
        provider="huggingface",
        message="Unexpected Hugging Face embedding response format.",
        error_type="response",
        retryable=False,
    )


def _request_error(provider: str, response: httpx.Response, model_config: ModelConfig) -> ProviderRequestError:
    details = {"status_code": response.status_code, "body": response.text[:500]}
    error_type = "auth" if response.status_code in {401, 403} else "transient"
    retryable = response.status_code in model_config.retry_policy.retryable_status_codes
    if response.status_code not in model_config.retry_policy.retryable_status_codes and error_type != "auth":
        error_type = "request"
    return ProviderRequestError(
        provider=provider,
        message="Hugging Face embedding request failed.",
        error_type=error_type,
        retryable=retryable,
        status_code=response.status_code,
        details=details,
    )


def _endpoint_url(base_url: str, model_name: str) -> str:
    normalized = base_url.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.netloc == "api-inference.huggingface.co" and "/pipeline/feature-extraction/" not in parsed.path:
        return f"https://router.huggingface.co/hf-inference/models/{model_name}/pipeline/feature-extraction"
    suffix = f"/{model_name}"
    if normalized.endswith(suffix):
        return normalized
    return f"{normalized}{suffix}"
