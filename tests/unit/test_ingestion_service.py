import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.core.config import Settings
from app.domain.entities.rag import IngestionTaskPayload
from app.services.ingestion_service import IngestionService


class _Repo:
    def __init__(self):
        self.updated_jobs = []

    async def get_document_for_ingestion(self, *, tenant_id, document_id):
        return {"id": document_id, "tenant_id": tenant_id}

    async def update_job(self, job_id, **kwargs):
        self.updated_jobs.append((job_id, kwargs))


def test_process_ingestion_payload_uses_dict_source_type():
    repo = _Repo()
    settings = Settings(
        _env_file=None,
        supabase_storage_url="https://example.supabase.co",
        supabase_storage_service_key="service-role",
    )
    service = IngestionService(
        repository=repo,
        model_router=SimpleNamespace(),
        storage=SimpleNamespace(),
        parser_registry=SimpleNamespace(),
        task_runner=SimpleNamespace(),
        telemetry=SimpleNamespace(record_ingestion_job=lambda **kwargs: None),
        settings=settings,
    )

    async def fake_extract(payload):
        return {"source_type": "markdown", "text": "hello"}

    async def fake_chunk(payload):
        return {"chunks_created": 1}

    async def fake_finalize(payload):
        return None

    service.extract_document_content = fake_extract  # type: ignore[method-assign]
    service.chunk_and_embed_document = fake_chunk  # type: ignore[method-assign]
    service.finalize_ingestion_job = fake_finalize  # type: ignore[method-assign]

    payload = IngestionTaskPayload(
        tenant_id=uuid4(),
        document_id=uuid4(),
        job_id=uuid4(),
    )

    asyncio.run(service.process_ingestion_payload(payload))

    assert repo.updated_jobs[0][1]["stage"] == "extract"
    assert repo.updated_jobs[1][1]["stage"] == "chunk"
    assert repo.updated_jobs[1][1]["stats"]["source_type"] == "markdown"
