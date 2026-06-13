import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

from app.api.schemas.documents import CreateDocumentRequest, CreateUploadUrlRequest, IngestDocumentRequest
from app.core.config import Settings
from app.services.document_service import DocumentService


class _DocumentRepo:
    def __init__(self):
        self.created_payload = None
        self.storage_update = None
        self.source_row = None

    async def create_document(self, payload, conn=None):
        self.created_payload = payload
        return uuid4()

    async def update_document_storage(self, payload, conn=None):
        self.storage_update = payload

    async def get_document_source(self, *, workspace_id, document_id, user_id):
        return self.source_row


class _IngestionRepo:
    def __init__(self):
        self.created_job = None

    async def create_ingestion_job(self, payload, conn=None):
        self.created_job = (payload.workspace_id, payload.document_id)
        return uuid4()

class _Connection:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True


class _Database:
    @asynccontextmanager
    async def connection(self):
        yield _Connection()


class _Storage:
    async def create_signed_upload_target(self, *, bucket: str, path: str, upsert: bool = False):
        return SimpleNamespace(bucket=bucket, path=path, upload_url="https://example/upload")


class _Ingestion:
    def __init__(self):
        self.inline_calls = []
        self.enqueued = []

    async def ingest_document(self, **payload):
        self.inline_calls.append(payload)
        return {"chunk_count": 1}

    async def enqueue_ingestion(self, payload):
        self.enqueued.append(payload)


def test_create_upload_target_infers_source_type_and_storage_path():
    repo = _DocumentRepo()
    ingestion_repo = _IngestionRepo()
    settings = Settings(
        _env_file=None,
        supabase_raw_bucket="raw-documents",
        supabase_storage_url="https://example.supabase.co",
        supabase_storage_service_key="service-role",
    )
    service = DocumentService(
        db=_Database(),
        document_repository=repo,
        ingestion_repository=ingestion_repo,
        ingestion_service=SimpleNamespace(),
        storage=_Storage(),
        settings=settings,
    )
    principal = SimpleNamespace(user_id=uuid4())

    response = asyncio.run(
        service.create_upload_target(
            uuid4(),
            principal,
            CreateUploadUrlRequest(filename="policy.pdf", content_type="application/pdf"),
        )
    )

    assert repo.created_payload.source_type == "pdf"
    assert response.bucket == "raw-documents"
    assert response.path.endswith("/raw/policy.pdf")


class _SignedPathStorage:
    async def create_signed_upload_target(self, *, bucket: str, path: str, upsert: bool = False):
        return SimpleNamespace(
            bucket=bucket,
            path=path,
            upload_url="https://example.supabase.co/object/upload/sign/raw-documents/path?token=abc",
        )


def test_create_upload_target_normalizes_signed_upload_url():
    repo = _DocumentRepo()
    ingestion_repo = _IngestionRepo()
    settings = Settings(
        _env_file=None,
        supabase_raw_bucket="raw-documents",
        supabase_storage_url="https://example.supabase.co",
        supabase_storage_service_key="service-role",
    )
    service = DocumentService(
        db=_Database(),
        document_repository=repo,
        ingestion_repository=ingestion_repo,
        ingestion_service=SimpleNamespace(),
        storage=_SignedPathStorage(),
        settings=settings,
    )
    principal = SimpleNamespace(user_id=uuid4())

    response = asyncio.run(
        service.create_upload_target(
            uuid4(),
            principal,
            CreateUploadUrlRequest(filename="policy.md", content_type="text/markdown"),
        )
    )

    assert response.upload_url == "https://example.supabase.co/storage/v1/object/upload/sign/raw-documents/path?token=abc"


def test_create_upload_target_infers_audio_source_type():
    repo = _DocumentRepo()
    ingestion_repo = _IngestionRepo()
    settings = Settings(
        _env_file=None,
        supabase_raw_bucket="raw-documents",
        supabase_storage_url="https://example.supabase.co",
        supabase_storage_service_key="service-role",
    )
    service = DocumentService(
        db=_Database(),
        document_repository=repo,
        ingestion_repository=ingestion_repo,
        ingestion_service=SimpleNamespace(),
        storage=_Storage(),
        settings=settings,
    )
    principal = SimpleNamespace(user_id=uuid4())

    response = asyncio.run(
        service.create_upload_target(
            uuid4(),
            principal,
            CreateUploadUrlRequest(filename="briefing.wav", content_type="audio/wav"),
        )
    )

    assert repo.created_payload.source_type == "audio"
    assert response.path.endswith("/raw/briefing.wav")


def test_create_text_document_sync_calls_ingest_document():
    repo = _DocumentRepo()
    ingestion_repo = _IngestionRepo()
    ingestion = _Ingestion()
    settings = Settings(
        _env_file=None,
        ingestion_inline_text_sync=True,
        supabase_storage_url="https://example.supabase.co",
        supabase_storage_service_key="service-role",
    )
    service = DocumentService(
        db=_Database(),
        document_repository=repo,
        ingestion_repository=ingestion_repo,
        ingestion_service=ingestion,
        storage=_Storage(),
        settings=settings,
    )
    principal = SimpleNamespace(user_id=uuid4())

    response = asyncio.run(
        service.create_text_document(
            uuid4(),
            principal,
            CreateDocumentRequest(title="Handbook", source_type="text", text="Remote work is allowed."),
        )
    )

    assert response.status == "indexed"
    assert len(ingestion.inline_calls) == 1
    assert ingestion.inline_calls[0]["text"] == "Remote work is allowed."


def test_create_text_document_async_enqueues_payload():
    repo = _DocumentRepo()
    ingestion_repo = _IngestionRepo()
    ingestion = _Ingestion()
    settings = Settings(
        _env_file=None,
        ingestion_inline_text_sync=False,
        supabase_storage_url="https://example.supabase.co",
        supabase_storage_service_key="service-role",
    )
    service = DocumentService(
        db=_Database(),
        document_repository=repo,
        ingestion_repository=ingestion_repo,
        ingestion_service=ingestion,
        storage=_Storage(),
        settings=settings,
    )
    principal = SimpleNamespace(user_id=uuid4())

    response = asyncio.run(
        service.create_text_document(
            uuid4(),
            principal,
            CreateDocumentRequest(title="Handbook", source_type="text", text="Remote work is allowed."),
        )
    )

    assert response.status == "queued"
    assert len(ingestion.enqueued) == 1


def test_reingest_text_document_sync_preserves_chunking_and_embedding_overrides():
    repo = _DocumentRepo()
    repo.source_row = SimpleNamespace(
        id=uuid4(),
        title="Handbook",
        source_type="text",
        sensitivity="internal",
        metadata={"_inline_text": "Remote work is allowed."},
    )
    ingestion_repo = _IngestionRepo()
    ingestion = _Ingestion()
    settings = Settings(
        _env_file=None,
        ingestion_inline_text_sync=True,
        supabase_storage_url="https://example.supabase.co",
        supabase_storage_service_key="service-role",
    )
    service = DocumentService(
        db=_Database(),
        document_repository=repo,
        ingestion_repository=ingestion_repo,
        ingestion_service=ingestion,
        storage=_Storage(),
        settings=settings,
    )
    principal = SimpleNamespace(user_id=uuid4())
    workspace_id = uuid4()
    document_id = uuid4()

    async def fake_get_job(workspace_id, job_id, principal):
        return SimpleNamespace(
            ingestion_job_id=job_id,
            document_id=document_id,
            status="succeeded",
            stage="finalize",
            attempts=1,
            stats={"chunk_count": 1},
            error_code=None,
            error_message=None,
        )

    service.get_job = fake_get_job

    asyncio.run(
        service.reingest_document(
            workspace_id,
            document_id,
            IngestDocumentRequest(
                force_reindex=True,
                chunking_version="hybrid-graph-v1",
                embedding_model="text-embedding-3-small",
            ),
            principal,
        )
    )

    assert len(ingestion.inline_calls) == 1
    assert ingestion.inline_calls[0]["chunking_version"] == "hybrid-graph-v1"
    assert ingestion.inline_calls[0]["embedding_model"] == "text-embedding-3-small"
