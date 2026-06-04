from __future__ import annotations

import asyncio
import json
import time
from statistics import median

import httpx

from app.core.runtime import configure_asyncio_runtime
from app.domain.errors import TooManyRequestsError
from app.llm.providers.base import ChatCompletion, EmbeddingResult
from app.main import create_app
from app.security.rate_limit import RateLimitDecision

configure_asyncio_runtime()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return ordered[index]


async def main() -> None:
    app = create_app()
    async with app.router.lifespan_context(app):
        container = app.state.container

        async def fake_embed_texts(texts: list[str]) -> EmbeddingResult:
            return EmbeddingResult(
                vectors=[[0.01] * container.settings.embedding_dimension for _ in texts],
                model_name="mock-embedding",
                provider="huggingface",
                input_tokens=64,
                estimated_cost_usd=0.0,
            )

        async def fake_complete_chat(messages: list[dict[str, str]], profile: str) -> ChatCompletion:
            return ChatCompletion(
                answer="The handbook answer is available in the indexed context [source:1].",
                model_name="mock-groq",
                provider="groq",
                input_tokens=128,
                output_tokens=32,
                estimated_cost_usd=0.0,
            )

        async def allow_rate_limit(**kwargs) -> RateLimitDecision:
            return RateLimitDecision(allowed=True, remaining=9999, retry_after_seconds=0)

        container.model_router.embed_texts = fake_embed_texts
        container.model_router.complete_chat = fake_complete_chat
        container.rate_limiter.check_request = allow_rate_limit

        transport = httpx.ASGITransport(app=app)
        headers = {"X-API-Key": container.settings.api_key}

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            document_response = await client.post(
                "/v1/documents",
                headers=headers,
                json={
                    "title": "load-probe-doc",
                    "source_type": "text",
                    "text": "Remote work is allowed three days per week with manager approval.",
                    "metadata": {"department": "hr"},
                    "sensitivity": "internal",
                },
            )
            document_response.raise_for_status()

            latencies_ms: list[float] = []
            statuses: dict[int, int] = {}
            total_requests = 20
            concurrency = 5
            semaphore = asyncio.Semaphore(concurrency)

            async def run_one(index: int) -> None:
                async with semaphore:
                    started = time.perf_counter()
                    response = await client.post(
                        "/v1/chat",
                        headers=headers,
                        json={
                            "query": f"load-probe-{index}: What is the remote work policy?",
                            "conversation_id": None,
                            "profile": "balanced",
                            "metadata": {"department": "hr"},
                        },
                    )
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    latencies_ms.append(elapsed_ms)
                    statuses[response.status_code] = statuses.get(response.status_code, 0) + 1
                    if response.status_code != 200:
                        raise TooManyRequestsError(
                            f"Unexpected status {response.status_code}",
                            details={"body": response.text},
                        )

            await asyncio.gather(*(run_one(index) for index in range(total_requests)))

        report = {
            "requests": total_requests,
            "concurrency": concurrency,
            "status_counts": statuses,
            "latency_ms": {
                "p50": round(_percentile(latencies_ms, 0.50), 2),
                "p95": round(_percentile(latencies_ms, 0.95), 2),
                "p99": round(_percentile(latencies_ms, 0.99), 2),
                "median": round(median(latencies_ms), 2),
                "max": round(max(latencies_ms), 2),
            },
        }
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
