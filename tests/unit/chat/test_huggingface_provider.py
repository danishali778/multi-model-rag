import httpx
import pytest

from app.llm.providers.base import ModelConfig, ProviderRequestError, RetryPolicy
from app.llm.providers.huggingface import _endpoint_url, _request_error


def test_endpoint_url_handles_base_and_model_qualified_urls():
    assert _endpoint_url(
        "https://api-inference.huggingface.co/models",
        "sentence-transformers/all-MiniLM-L6-v2",
    ) == "https://router.huggingface.co/hf-inference/models/sentence-transformers/all-MiniLM-L6-v2/pipeline/feature-extraction"
    assert _endpoint_url(
        "https://api-inference.huggingface.co/models/sentence-transformers/all-MiniLM-L6-v2",
        "sentence-transformers/all-MiniLM-L6-v2",
    ) == "https://router.huggingface.co/hf-inference/models/sentence-transformers/all-MiniLM-L6-v2/pipeline/feature-extraction"


def test_request_error_maps_auth_failures():
    response = httpx.Response(403, text='{"error":"forbidden"}')
    config = ModelConfig(
        profile="embedding",
        provider="huggingface",
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        timeout_seconds=60,
        max_output_tokens=1,
        retry_policy=RetryPolicy(max_retries=1, retryable_status_codes=(429, 500, 503)),
    )

    error = _request_error("huggingface", response, config)

    assert isinstance(error, ProviderRequestError)
    assert error.error_type == "auth"
    assert error.retryable is False
    assert error.status_code == 403
