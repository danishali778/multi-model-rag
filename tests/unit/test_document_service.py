import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.api.schemas.documents import CreateUploadUrlRequest
from app.core.config import Settings
from app.services.document_service import DocumentService


class _Repo:
    def __init__(self):
        self.created_payload = None
        self.storage_update = None

    async def create_document(self, **payload):
        self.created_payload = payload
        return uuid4()

    async def update_document_storage(self, **payload):
        self.storage_update = payload

    async def set_document_acl_groups(self, **payload):
        return None


class _Storage:
    async def create_signed_upload_target(self, *, bucket: str, path: str, upsert: bool = False):
        return SimpleNamespace(bucket=bucket, path=path, upload_url="https://example/upload")


def test_create_upload_target_infers_source_type_and_storage_path():
    repo = _Repo()
    settings = Settings(
        _env_file=None,
        supabase_raw_bucket="raw-documents",
        supabase_storage_url="https://example.supabase.co",
        supabase_storage_service_key="service-role",
    )
    service = DocumentService(
        repository=repo,
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

    assert repo.created_payload["source_type"] == "pdf"
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
    repo = _Repo()
    settings = Settings(
        _env_file=None,
        supabase_raw_bucket="raw-documents",
        supabase_storage_url="https://example.supabase.co",
        supabase_storage_service_key="service-role",
    )
    service = DocumentService(
        repository=repo,
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
