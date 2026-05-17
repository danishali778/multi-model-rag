from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.llm.providers.base import ChatCompletion, ChatProvider, ModelConfig, ProviderRequestError


class GroqChatProvider(ChatProvider):
    provider_name = "groq"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def complete_chat(self, messages: list[dict[str, str]], model_config: ModelConfig) -> ChatCompletion:
        if not self.settings.groq_api_key:
            raise ProviderRequestError(
                provider=self.provider_name,
                message="Groq API key is not configured.",
                error_type="auth",
                retryable=False,
            )
        headers = {
            "Authorization": f"Bearer {self.settings.groq_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_config.model_name,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": model_config.max_output_tokens,
        }
        async with httpx.AsyncClient(timeout=model_config.timeout_seconds) as client:
            response = await client.post(
                f"{str(self.settings.groq_base_url).rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
        if response.status_code >= 400:
            raise _request_error(self.provider_name, response, model_config)
        data = response.json()
        choice = _message_content(data["choices"][0]["message"]["content"])
        usage = data.get("usage", {})
        return ChatCompletion(
            answer=choice,
            model_name=data.get("model", model_config.model_name),
            provider=self.provider_name,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            estimated_cost_usd=0.0,
        )

    async def health_check(self) -> bool:
        return bool(self.settings.groq_api_key)


def _request_error(provider: str, response: httpx.Response, model_config: ModelConfig) -> ProviderRequestError:
    details = {"status_code": response.status_code, "body": response.text[:500]}
    error_type = "auth" if response.status_code in {401, 403} else "transient"
    retryable = response.status_code in model_config.retry_policy.retryable_status_codes
    if response.status_code not in model_config.retry_policy.retryable_status_codes and error_type != "auth":
        error_type = "request"
    return ProviderRequestError(
        provider=provider,
        message="Groq chat completion failed.",
        error_type=error_type,
        retryable=retryable,
        status_code=response.status_code,
        details=details,
    )


def _message_content(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        fragments: list[str] = []
        for item in payload:
            if isinstance(item, dict) and item.get("type") == "text":
                fragments.append(str(item.get("text", "")))
        return "".join(fragments)
    return str(payload)
