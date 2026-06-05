from __future__ import annotations

import asyncio
import os
from dataclasses import asdict
from typing import Any

from celery import Celery
from prometheus_client import start_http_server

from app.core.config import Settings, get_settings
from app.domain.entities.rag import IngestionTaskPayload
from app.domain.errors import RetryableIngestionError
from app.storage.models.ingestion import IngestionJobUpdateInput


def build_celery_app(settings: Settings | None = None) -> Celery:
    active_settings = settings or get_settings()
    app = Celery(
        "multi_model_rag",
        broker=active_settings.effective_celery_broker_url,
        backend=active_settings.effective_celery_result_backend,
    )
    app.conf.task_always_eager = active_settings.celery_task_always_eager
    app.conf.task_eager_propagates = True
    app.conf.task_serializer = "json"
    app.conf.result_serializer = "json"
    app.conf.accept_content = ["json"]
    return app


celery_app = build_celery_app()
_WORKER_METRICS_STARTED = False


def _start_worker_metrics_server(settings: Settings) -> None:
    global _WORKER_METRICS_STARTED
    if _WORKER_METRICS_STARTED:
        return
    if settings.runtime_role != "worker" or not settings.worker_metrics_enabled:
        return
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        return
    start_http_server(settings.worker_metrics_port)
    _WORKER_METRICS_STARTED = True


_start_worker_metrics_server(get_settings())


class IngestionTaskRunner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.app = build_celery_app(settings)

    async def enqueue_ingestion_job(self, payload: IngestionTaskPayload) -> None:
        if self.settings.celery_task_always_eager:
            await _run_async_task_async("process_ingestion_payload", asdict(payload))
            return
        ingest_document_job.delay(asdict(payload))

    async def requeue_dead_letter_job(self, payload: IngestionTaskPayload) -> None:
        if self.settings.celery_task_always_eager:
            await _run_async_task_async("requeue_dead_letter_job", asdict(payload))
            return
        requeue_dead_letter_job.delay(asdict(payload))


@celery_app.task(bind=True, name="ingest_document_job", max_retries=3)
def ingest_document_job(self, payload: dict[str, Any]) -> None:
    settings = get_settings()
    task_payload = IngestionTaskPayload(**payload)
    try:
        _run_async_task("process_ingestion_payload", payload)
    except RetryableIngestionError as exc:
        attempt_number = self.request.retries + 1
        status = "retrying" if attempt_number <= settings.celery_max_retries else "dead_letter"
        _update_job_failure(task_payload, status=status, error_message=exc.message, attempts=attempt_number, stats=exc.details)
        if attempt_number <= settings.celery_max_retries:
            raise self.retry(exc=exc, countdown=settings.celery_retry_backoff_seconds * attempt_number)
        raise
    except Exception as exc:  # noqa: BLE001
        _update_job_failure(
            task_payload,
            status="dead_letter",
            error_message=str(exc),
            attempts=self.request.retries + 1,
            stats={"terminal": True},
        )
        raise


@celery_app.task(bind=True, name="extract_document_content", max_retries=3)
def extract_document_content(self, payload: dict[str, Any]) -> dict[str, Any]:
    return _run_async_task("extract_document_content", payload)


@celery_app.task(bind=True, name="chunk_and_embed_document", max_retries=3)
def chunk_and_embed_document(self, payload: dict[str, Any]) -> dict[str, Any]:
    return _run_async_task("chunk_and_embed_document", payload)


@celery_app.task(bind=True, name="finalize_ingestion_job", max_retries=3)
def finalize_ingestion_job(self, payload: dict[str, Any]) -> None:
    _run_async_task("finalize_ingestion_job", payload)


@celery_app.task(bind=True, name="requeue_dead_letter_job", max_retries=3)
def requeue_dead_letter_job(self, payload: dict[str, Any]) -> None:
    _run_async_task("requeue_dead_letter_job", payload)


def _run_async_task(method_name: str, payload: dict[str, Any]) -> Any:
    return asyncio.run(_run_async_task_async(method_name, payload))


async def _run_async_task_async(method_name: str, payload: dict[str, Any]) -> Any:
    from app.core.container import AppContainer

    settings = get_settings()
    container = AppContainer(settings)
    task_payload = IngestionTaskPayload(**payload)

    try:
        await container.db.startup()
        method = getattr(container.ingestion_service, method_name)
        return await method(task_payload)
    except RetryableIngestionError as exc:
        raise exc
    finally:
        await container.db.shutdown()


def _update_job_failure(
    payload: IngestionTaskPayload,
    *,
    status: str,
    error_message: str,
    attempts: int,
    stats: dict[str, Any],
) -> None:
    from app.core.container import AppContainer

    settings = get_settings()
    container = AppContainer(settings)

    async def runner():
        await container.db.startup()
        try:
            await container.ingestion_repository.update_job(
                payload.job_id,
                IngestionJobUpdateInput(
                    status=status,
                    stage="failed",
                    attempts=attempts,
                    error_code="ingestion_error",
                    error_message=error_message,
                    stats=stats,
                ),
            )
            container.telemetry.record_ingestion_job(status=status, stage="failed")
        finally:
            await container.db.shutdown()

    asyncio.run(runner())
