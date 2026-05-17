from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
except ImportError:  # pragma: no cover - handled in constrained environments
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    class _Metric:
        def __init__(self, name: str):
            self.name = name
            self.values: list[tuple[tuple[str, ...], float]] = []

        def labels(self, **labels):
            metric = self

            class _BoundMetric:
                def inc(self, amount: float = 1.0) -> None:
                    metric.values.append((tuple(f"{key}={value}" for key, value in labels.items()), amount))

                def observe(self, amount: float) -> None:
                    metric.values.append((tuple(f"{key}={value}" for key, value in labels.items()), amount))

            return _BoundMetric()

    def Counter(name: str, *_args, **_kwargs):
        return _Metric(name)

    def Histogram(name: str, *_args, **_kwargs):
        return _Metric(name)

    def generate_latest() -> bytes:
        lines = []
        for metric in (REQUEST_COUNT, REQUEST_LATENCY, MODEL_CALLS, MODEL_TOKENS, MODEL_COST, INGESTION_JOBS, FEEDBACK_COUNT, RETRIEVAL_COUNT, RETRIEVAL_LATENCY):
            total = sum(value for _labels, value in metric.values)
            lines.append(f"{metric.name} {total}")
        return ("\n".join(lines) + "\n").encode("utf-8")

from app.core.config import Settings

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
except ImportError:  # pragma: no cover - handled at runtime after deps install
    trace = None
    Resource = None
    TracerProvider = None
    BatchSpanProcessor = None
    ConsoleSpanExporter = None


REQUEST_COUNT = Counter(
    "rag_api_requests_total",
    "Total API requests.",
    ["method", "route", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "rag_api_request_duration_seconds",
    "API request latency.",
    ["method", "route"],
)
MODEL_CALLS = Counter(
    "rag_model_calls_total",
    "Model provider call count.",
    ["operation", "provider", "profile", "status"],
)
MODEL_TOKENS = Counter(
    "rag_model_tokens_total",
    "Model token totals.",
    ["operation", "provider", "profile", "direction"],
)
MODEL_COST = Counter(
    "rag_model_cost_usd_total",
    "Estimated model cost.",
    ["operation", "provider", "profile"],
)
INGESTION_JOBS = Counter(
    "rag_ingestion_jobs_total",
    "Ingestion job state transitions.",
    ["status", "stage"],
)
FEEDBACK_COUNT = Counter(
    "rag_feedback_total",
    "Feedback submissions.",
    ["rating"],
)
RETRIEVAL_COUNT = Counter(
    "rag_retrieval_requests_total",
    "Retrieval requests by outcome.",
    ["outcome"],
)
RETRIEVAL_LATENCY = Histogram(
    "rag_retrieval_duration_seconds",
    "Retrieval latency.",
    ["mode"],
)


@dataclass(slots=True)
class MetricsSnapshot:
    retrieval_latency_ms: int | None = None
    generation_latency_ms: int | None = None


class Telemetry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._provider_initialized = False

    def setup(self) -> None:
        if self._provider_initialized or not self.settings.tracing_enabled or trace is None:
            return
        resource = Resource.create({"service.name": self.settings.telemetry_service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        self._provider_initialized = True

    def tracer(self, name: str):
        if trace is None:
            return _NullTracer()
        return trace.get_tracer(name)

    def record_http_request(self, *, method: str, route: str, status_code: int, duration_seconds: float) -> None:
        REQUEST_COUNT.labels(method=method, route=route, status_code=status_code).inc()
        REQUEST_LATENCY.labels(method=method, route=route).observe(duration_seconds)

    def record_model_usage(
        self,
        *,
        operation: str,
        provider: str,
        profile: str,
        status: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        MODEL_CALLS.labels(operation=operation, provider=provider, profile=profile, status=status).inc()
        MODEL_TOKENS.labels(operation=operation, provider=provider, profile=profile, direction="input").inc(input_tokens)
        MODEL_TOKENS.labels(operation=operation, provider=provider, profile=profile, direction="output").inc(output_tokens)
        MODEL_COST.labels(operation=operation, provider=provider, profile=profile).inc(estimated_cost_usd)

    def record_ingestion_job(self, *, status: str, stage: str) -> None:
        INGESTION_JOBS.labels(status=status, stage=stage).inc()

    def record_feedback(self, *, rating: str) -> None:
        FEEDBACK_COUNT.labels(rating=rating).inc()

    def record_retrieval(self, *, outcome: str, mode: str, duration_seconds: float) -> None:
        RETRIEVAL_COUNT.labels(outcome=outcome).inc()
        RETRIEVAL_LATENCY.labels(mode=mode).observe(duration_seconds)

    def metrics_payload(self) -> tuple[bytes, str]:
        return generate_latest(), CONTENT_TYPE_LATEST


class _NullSpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        return None


class _NullTracer:
    def start_as_current_span(self, name: str):
        return _NullSpan()


class Timer:
    def __init__(self):
        self.started = time.perf_counter()

    @property
    def elapsed_seconds(self) -> float:
        return time.perf_counter() - self.started

    @property
    def elapsed_ms(self) -> int:
        return int(self.elapsed_seconds * 1000)
