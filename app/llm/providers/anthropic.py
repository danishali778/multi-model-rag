from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.llm.providers.base import ChatCompletion, ChatProvider, ModelConfig, ProviderRequestError


class AnthropicChatProvider(ChatProvider):
    provider_name = "anthropic"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def complete_chat(self, messages: list[dict[str, str]], model_config: ModelConfig) -> ChatCompletion:
        if not self.settings.anthropic_api_key:
            raise ProviderRequestError(
                provider=self.provider_name,
                message="Anthropic API key is not configured.",
                error_type="auth",
                retryable=False,
            )
        system_prompt, conversation = _split_messages(messages)
        headers = {
            "x-api-key": self.settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model_config.model_name,
            "max_tokens": model_config.max_output_tokens,
            "temperature": 0.1,
            "messages": conversation,
        }
        if system_prompt:
            payload["system"] = system_prompt
        async with httpx.AsyncClient(timeout=model_config.timeout_seconds) as client:
            response = await client.post(
                f"{str(self.settings.anthropic_base_url).rstrip('/')}/messages",
                headers=headers,
                json=payload,
            )
        if response.status_code >= 400:
            raise _request_error(response, model_config)
        data = response.json()
        usage = data.get("usage", {})
        return ChatCompletion(
            answer="".join(item.get("text", "") for item in data.get("content", []) if item.get("type") == "text"),
            model_name=data.get("model", model_config.model_name),
            provider=self.provider_name,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            estimated_cost_usd=0.0,
        )

    async def health_check(self) -> bool:
        return bool(self.settings.anthropic_api_key)


def _split_messages(messages: list[dict[str, str]]) -> tuple[str | None, list[dict[str, str]]]:
    system_parts: list[str] = []
    conversation: list[dict[str, str]] = []
    for message in messages:
        if message["role"] == "system":
            system_parts.append(message["content"])
            continue
        conversation.append({"role": message["role"], "content": message["content"]})
    return ("\n\n".join(system_parts) or None, conversation)


def _request_error(response: httpx.Response, model_config: ModelConfig) -> ProviderRequestError:
    details = {"status_code": response.status_code, "body": response.text[:500]}
    error_type = "auth" if response.status_code in {401, 403} else "transient"
    retryable = response.status_code in model_config.retry_policy.retryable_status_codes
    if response.status_code not in model_config.retry_policy.retryable_status_codes and error_type != "auth":
        error_type = "request"
    return ProviderRequestError(
        provider="anthropic",
        message="Anthropic chat completion failed.",
        error_type=error_type,
        retryable=retryable,
        status_code=response.status_code,
        details=details,
    )
