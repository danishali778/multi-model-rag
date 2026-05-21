import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

from app.core.config import Settings
from app.domain.entities.rag import IngestionTaskPayload
from app.services.ingestion_service import IngestionService
from app.storage.models.ingestion import IngestionJobUpdateInput


@dataclass(slots=True)
class _Document:
    id: object
    workspace_id: object
    title: str = "Doc"
    source_type: str = "text"
    source_uri: str | None = None
    storage_bucket: str | None = None
    storage_path: str | None = None
    content_hash: str | None = None
    status: str = "pending"
    sensitivity: str = "internal"
    metadata: dict = None


class _DocumentRepo:
    def __init__(self):
        self.documents = []

    async def get_document_for_ingestion(self, *, workspace_id, document_id):
        return _Document(id=document_id, workspace_id=workspace_id, metadata={})


class _IngestionRepo:
    def __init__(self):
        self.updated_jobs = []

    async def update_job(self, job_id, payload: IngestionJobUpdateInput):
        self.updated_jobs.append((job_id, payload))


def test_process_ingestion_payload_uses_dict_source_type():
    document_repo = _DocumentRepo()
    ingestion_repo = _IngestionRepo()
    settings = Settings(
        _env_file=None,
        supabase_storage_url="https://example.supabase.co",
        supabase_storage_service_key="service-role",
    )
    service = IngestionService(
        document_repository=document_repo,
        ingestion_repository=ingestion_repo,
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
        workspace_id=uuid4(),
        document_id=uuid4(),
        job_id=uuid4(),
    )

    asyncio.run(service.process_ingestion_payload(payload))

    assert ingestion_repo.updated_jobs[0][1].stage == "extract"
    assert ingestion_repo.updated_jobs[1][1].stage == "chunk"
    assert ingestion_repo.updated_jobs[1][1].stats["source_type"] == "markdown"
