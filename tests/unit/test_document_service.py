import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.api.schemas.documents import CreateDocumentRequest, CreateUploadUrlRequest
from app.core.config import Settings
from app.services.document_service import DocumentService


class _DocumentRepo:
    def __init__(self):
        self.created_payload = None
        self.storage_update = None

    async def create_document(self, payload):
        self.created_payload = payload
        return uuid4()

    async def update_document_storage(self, payload):
        self.storage_update = payload


class _IngestionRepo:
    def __init__(self):
        self.created_job = None

    async def create_ingestion_job(self, payload):
        self.created_job = (payload.workspace_id, payload.document_id)
        return uuid4()



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
