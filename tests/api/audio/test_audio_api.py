import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.api.dependencies import WorkspaceContext
from app.api.routes.audio import create_audio_upload_url, get_audio_document, ingest_audio_document
from app.api.schemas.audio import (
    AudioDocumentDetailResponse,
    AudioDocumentMetadataResponse,
    CreateAudioUploadUrlRequest,
    CreateAudioUploadUrlResponse,
    IngestAudioDocumentRequest,
    IngestionJobResponse,
)
from app.domain.entities.rag import Principal


class _IdempotencyService:
    def __init__(self):
        self.calls = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return await kwargs["execute"]()


def _context(audio_ingestion_service) -> WorkspaceContext:
    return WorkspaceContext(
        container=SimpleNamespace(audio_ingestion_service=audio_ingestion_service, idempotency_service=_IdempotencyService()),
        principal=Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key", role="owner"),
        workspace_id=uuid4(),
    )


def test_create_audio_upload_url_routes_to_audio_service():
    expected = CreateAudioUploadUrlResponse(
        bucket="raw-documents",
        path="workspaces/x/documents/y/raw/briefing.wav",
        upload_url="https://example/upload",
        document_id=uuid4(),
    )

    async def fake_create_upload_target(workspace_id, principal, payload):
        assert payload.filename == "briefing.wav"
        return expected

    response = asyncio.run(
        create_audio_upload_url(
            CreateAudioUploadUrlRequest(filename="briefing.wav", content_type="audio/wav"),
            _context(SimpleNamespace(create_upload_target=fake_create_upload_target)),
        )
    )

    assert response == expected


def test_get_audio_document_routes_to_audio_service():
    document_id = uuid4()
    now = datetime.now(UTC)
    expected = AudioDocumentDetailResponse(
        id=document_id,
        title="Daily Briefing",
        source_type="audio",
        status="indexed",
        metadata={},
        chunk_count=3,
        audio=AudioDocumentMetadataResponse(
            audio_bucket="raw-documents",
            audio_path="workspaces/x/documents/y/raw/briefing.wav",
            mime_type="audio/wav",
            audio_format="wav",
            estimated_duration_ms=4200,
            transcript_language="en",
            transcription_provider="openai",
            transcription_model="gpt-4o-mini-transcribe",
            segment_count=2,
            warning_count=0,
            warnings=[],
            metadata={},
            created_at=now,
            updated_at=now,
        ),
    )

    async def fake_get_audio_document(workspace_id, requested_document_id, principal):
        assert requested_document_id == document_id
        return expected

    response = asyncio.run(
        get_audio_document(document_id, _context(SimpleNamespace(get_audio_document=fake_get_audio_document)))
    )

    assert response == expected


def test_ingest_audio_document_routes_to_audio_service():
    document_id = uuid4()
    expected = IngestionJobResponse(
        ingestion_job_id=uuid4(),
        document_id=document_id,
        status="queued",
        stage="queued",
        attempts=1,
    )

    async def fake_reingest_audio_document(workspace_id, requested_document_id, payload, principal):
        assert requested_document_id == document_id
        assert payload.force_reindex is True
        return expected

    response = asyncio.run(
        ingest_audio_document(
            document_id,
            IngestAudioDocumentRequest(force_reindex=True),
            _context(SimpleNamespace(reingest_audio_document=fake_reingest_audio_document)),
        )
    )

    assert response == expected


def test_create_audio_upload_url_uses_idempotency_service_when_key_present():
    expected = CreateAudioUploadUrlResponse(
        bucket="raw-documents",
        path="workspaces/x/documents/y/raw/briefing.wav",
        upload_url="https://example/upload",
        document_id=uuid4(),
    )

    async def fake_create_upload_target(workspace_id, principal, payload):
        assert payload.filename == "briefing.wav"
        return expected

    idempotency = _IdempotencyService()
    context = WorkspaceContext(
        container=SimpleNamespace(
            audio_ingestion_service=SimpleNamespace(create_upload_target=fake_create_upload_target),
            idempotency_service=idempotency,
        ),
        principal=Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key", role="owner"),
        workspace_id=uuid4(),
    )

    response = asyncio.run(
        create_audio_upload_url(
            CreateAudioUploadUrlRequest(filename="briefing.wav", content_type="audio/wav"),
            context,
            idempotency_key="idem-audio-1",
        )
    )

    assert response == expected
    assert idempotency.calls[0]["idempotency_key"] == "idem-audio-1"
    assert idempotency.calls[0]["route_key"] == "/v1/audio/documents/upload-url"
