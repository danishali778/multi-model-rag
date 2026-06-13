import asyncio
from datetime import datetime, UTC
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.dependencies import WorkspaceContext
from app.api.routes.documents import (
    create_document,
    create_upload_url,
    get_document,
    get_ingestion_job,
    ingest_document,
    list_documents,
    list_ingestion_jobs,
)
from app.api.schemas.documents import (
    CreateDocumentRequest,
    CreateDocumentResponse,
    CreateUploadUrlRequest,
    CreateUploadUrlResponse,
    DocumentDetailResponse,
    DocumentListItem,
    DocumentListResponse,
    IngestDocumentRequest,
    IngestionJobListItem,
    IngestionJobListResponse,
    IngestionJobResponse,
)
from app.domain.entities.rag import Principal


class _IdempotencyService:
    def __init__(self):
        self.calls = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return await kwargs["execute"]()


def _context(document_service) -> WorkspaceContext:
    return WorkspaceContext(
        container=SimpleNamespace(document_service=document_service, idempotency_service=_IdempotencyService()),
        principal=Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key", role="owner"),
        workspace_id=uuid4(),
    )


def test_create_document_routes_to_document_service():
    expected = CreateDocumentResponse(document_id=uuid4(), status="indexed", ingestion_job_id=uuid4())

    async def fake_create_text_document(workspace_id, principal, payload):
        assert payload.title == "Handbook"
        return expected

    response = asyncio.run(
        create_document(
            CreateDocumentRequest(title="Handbook", source_type="text", text="Remote work is allowed."),
            _context(SimpleNamespace(create_text_document=fake_create_text_document)),
        )
    )

    assert response == expected


def test_create_upload_url_normalizes_signed_path():
    expected = CreateUploadUrlResponse(
        bucket="raw-documents",
        path="workspaces/1/documents/2/raw/policy.pdf",
        upload_url="https://example.supabase.co/object/upload/sign/raw-documents/path?token=abc",
        document_id=uuid4(),
    )

    async def fake_create_upload_target(workspace_id, principal, payload):
        assert payload.filename == "policy.pdf"
        return expected

    response = asyncio.run(
        create_upload_url(
            CreateUploadUrlRequest(filename="policy.pdf", content_type="application/pdf"),
            _context(SimpleNamespace(create_upload_target=fake_create_upload_target)),
        )
    )

    assert response.upload_url == "https://example.supabase.co/storage/v1/object/upload/sign/raw-documents/path?token=abc"


def test_list_documents_forwards_filters_and_limit():
    now = datetime.now(UTC)
    expected = DocumentListResponse(
        items=[
            DocumentListItem(
                id=uuid4(),
                title="Handbook",
                source_type="text",
                status="indexed",
                sensitivity="internal",
                created_at=now,
                updated_at=now,
            )
        ]
    )

    async def fake_list_documents(**kwargs):
        assert kwargs["status"] == "indexed"
        assert kwargs["source_type"] == "text"
        assert kwargs["limit"] == 10
        return expected

    response = asyncio.run(
        list_documents(
            status="indexed",
            source_type="text",
            limit=10,
            context=_context(SimpleNamespace(list_documents=fake_list_documents)),
        )
    )

    assert response == expected


def test_get_document_routes_to_document_service():
    document_id = uuid4()
    expected = DocumentDetailResponse(
        id=document_id,
        title="Handbook",
        source_type="text",
        status="indexed",
        metadata={"department": "hr"},
        chunk_count=2,
    )

    async def fake_get_document(workspace_id, requested_document_id, principal):
        assert requested_document_id == document_id
        return expected

    response = asyncio.run(
        get_document(document_id, _context(SimpleNamespace(get_document=fake_get_document)))
    )

    assert response == expected


def test_ingest_document_routes_payload_to_service():
    document_id = uuid4()
    expected = IngestionJobResponse(
        ingestion_job_id=uuid4(),
        document_id=document_id,
        status="queued",
        stage="queued",
        attempts=0,
    )

    async def fake_reingest_document(workspace_id, requested_document_id, payload, principal):
        assert requested_document_id == document_id
        assert payload.force_reindex is True
        return expected

    response = asyncio.run(
        ingest_document(
            document_id,
            IngestDocumentRequest(force_reindex=True),
            _context(SimpleNamespace(reingest_document=fake_reingest_document)),
        )
    )

    assert response == expected


def test_list_ingestion_jobs_routes_to_document_service():
    now = datetime.now(UTC)
    expected = IngestionJobListResponse(
        items=[
            IngestionJobListItem(
                id=uuid4(),
                document_id=uuid4(),
                status="succeeded",
                stage="finalize",
                attempts=1,
                created_at=now,
            )
        ]
    )

    async def fake_list_jobs(workspace_id, principal, limit):
        assert limit == 25
        return expected

    response = asyncio.run(
        list_ingestion_jobs(limit=25, context=_context(SimpleNamespace(list_jobs=fake_list_jobs)))
    )

    assert response == expected


def test_get_ingestion_job_routes_to_document_service():
    job_id = uuid4()
    expected = IngestionJobResponse(
        ingestion_job_id=job_id,
        document_id=uuid4(),
        status="succeeded",
        stage="finalize",
        attempts=1,
    )

    async def fake_get_job(workspace_id, requested_job_id, principal):
        assert requested_job_id == job_id
        return expected

    response = asyncio.run(
        get_ingestion_job(job_id, _context(SimpleNamespace(get_job=fake_get_job)))
    )

    assert response == expected


def test_create_document_uses_idempotency_service_when_key_present():
    expected = CreateDocumentResponse(document_id=uuid4(), status="indexed", ingestion_job_id=uuid4())

    async def fake_create_text_document(workspace_id, principal, payload):
        assert payload.title == "Handbook"
        return expected

    idempotency = _IdempotencyService()
    context = WorkspaceContext(
        container=SimpleNamespace(
            document_service=SimpleNamespace(create_text_document=fake_create_text_document),
            idempotency_service=idempotency,
        ),
        principal=Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key", role="owner"),
        workspace_id=uuid4(),
    )

    response = asyncio.run(
        create_document(
            CreateDocumentRequest(title="Handbook", source_type="text", text="Remote work is allowed."),
            context,
            idempotency_key="idem-doc-1",
        )
    )

    assert response == expected
    assert idempotency.calls[0]["idempotency_key"] == "idem-doc-1"
    assert idempotency.calls[0]["route_key"] == "/v1/documents"
    assert idempotency.calls[0]["request_body"]["title"] == "Handbook"


def test_create_document_request_rejects_unsupported_source_type():
    with pytest.raises(ValidationError):
        CreateDocumentRequest(title="Handbook", source_type="pdf", text="Remote work is allowed.")


def test_create_upload_url_request_rejects_mismatched_source_type():
    with pytest.raises(ValidationError):
        CreateUploadUrlRequest(
            filename="policy.pdf",
            content_type="application/pdf",
            source_type="docx",
        )
