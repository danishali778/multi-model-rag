from __future__ import annotations

import httpx

from app.core.config import Settings
from app.llm.providers.base import ChatCompletion, ChatProvider, ModelConfig, ProviderRequestError


class OllamaChatProvider(ChatProvider):
    provider_name = "ollama"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def complete_chat(self, messages: list[dict[str, str]], model_config: ModelConfig) -> ChatCompletion:
        payload = {
            "model": model_config.model_name,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": model_config.max_output_tokens},
        }
        async with httpx.AsyncClient(timeout=model_config.timeout_seconds) as client:
            response = await client.post(
                f"{str(self.settings.ollama_base_url).rstrip('/')}/api/chat",
                json=payload,
            )
        if response.status_code >= 400:
            raise _request_error(response, model_config)
        data = response.json()
        prompt_eval_count = int(data.get("prompt_eval_count", 0))
        eval_count = int(data.get("eval_count", 0))
        message = data.get("message", {})
        return ChatCompletion(
            answer=str(message.get("content", "")),
            model_name=data.get("model", model_config.model_name),
            provider=self.provider_name,
            input_tokens=prompt_eval_count,
            output_tokens=eval_count,
            estimated_cost_usd=0.0,
        )

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{str(self.settings.ollama_base_url).rstrip('/')}/api/tags")
            return response.status_code < 500
        except httpx.HTTPError:
            return False


def _request_error(response: httpx.Response, model_config: ModelConfig) -> ProviderRequestError:
    details = {"status_code": response.status_code, "body": response.text[:500]}
    error_type = "auth" if response.status_code in {401, 403} else "transient"
    retryable = response.status_code in model_config.retry_policy.retryable_status_codes
    if response.status_code not in model_config.retry_policy.retryable_status_codes and error_type != "auth":
        error_type = "request"
    return ProviderRequestError(
        provider="ollama",
        message="Ollama chat completion failed.",
        error_type=error_type,
        retryable=retryable,
        status_code=response.status_code,
        details=details,
    )
