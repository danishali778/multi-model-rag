import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.domain.entities.rag import IngestionTaskPayload
from app.workers import tasks
from app.workers.tasks import IngestionTaskRunner


def test_enqueue_ingestion_job_serializes_slotted_payload(monkeypatch):
    captured = {}

    def fake_delay(payload):
        captured["payload"] = payload

    monkeypatch.setattr(tasks, "ingest_document_job", SimpleNamespace(delay=fake_delay))

    runner = IngestionTaskRunner.__new__(IngestionTaskRunner)
    runner.settings = SimpleNamespace(celery_task_always_eager=False)
    payload = IngestionTaskPayload(
        workspace_id=uuid4(),
        document_id=uuid4(),
        job_id=uuid4(),
        force_reindex=True,
    )

    asyncio.run(runner.enqueue_ingestion_job(payload))

    assert captured["payload"]["workspace_id"] == payload.workspace_id
    assert captured["payload"]["document_id"] == payload.document_id
    assert captured["payload"]["job_id"] == payload.job_id
    assert captured["payload"]["force_reindex"] is True


def test_enqueue_ingestion_job_runs_directly_when_eager(monkeypatch):
    captured = {}

    async def fake_run_async_task_async(method_name, payload):
        captured["method_name"] = method_name
        captured["payload"] = payload

    def fail_delay(payload):
        raise AssertionError("delay should not be called in eager mode")

    monkeypatch.setattr(tasks, "_run_async_task_async", fake_run_async_task_async)
    monkeypatch.setattr(tasks, "ingest_document_job", SimpleNamespace(delay=fail_delay))

    runner = IngestionTaskRunner.__new__(IngestionTaskRunner)
    runner.settings = SimpleNamespace(celery_task_always_eager=True)
    payload = IngestionTaskPayload(
        workspace_id=uuid4(),
        document_id=uuid4(),
        job_id=uuid4(),
    )

    asyncio.run(runner.enqueue_ingestion_job(payload))

    assert captured["method_name"] == "process_ingestion_payload"
    assert captured["payload"]["workspace_id"] == payload.workspace_id
