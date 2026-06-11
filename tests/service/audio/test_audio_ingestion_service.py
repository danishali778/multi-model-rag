import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.api.schemas.audio import CreateAudioUploadUrlRequest, IngestAudioDocumentRequest
from app.core.config import Settings
from app.services.audio_ingestion_service import AudioIngestionService
from app.storage.models.audio import AudioDocumentRow
from app.storage.models.document import DocumentDetailRow, DocumentSourceRow


class _DocumentRepo:
    def __init__(self):
        self.created_payload = None
        self.storage_update = None

    async def create_document(self, payload, conn=None):
        self.created_payload = payload
        self.document_id = uuid4()
        return self.document_id

    async def update_document_storage(self, payload, conn=None):
        self.storage_update = payload

    async def get_document(self, *, workspace_id, document_id, user_id):
        return DocumentDetailRow(
            id=document_id,
            title="Daily Briefing",
            source_type="audio",
            status="indexed",
            metadata={"department": "ops"},
            chunk_count=3,
        )

    async def get_document_source(self, *, workspace_id, document_id, user_id):
        return DocumentSourceRow(
            id=document_id,
            title="Daily Briefing",
            source_type="audio",
            sensitivity="internal",
            metadata={},
        )


class _AudioRepo:
    def __init__(self):
        self.created_payload = None

    async def create_audio_document(self, payload, conn=None):
        self.created_payload = payload

    async def get_audio_document(self, *, workspace_id, document_id):
        now = datetime.now(UTC)
        return AudioDocumentRow(
            id=uuid4(),
            workspace_id=workspace_id,
            document_id=document_id,
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
            metadata={"filename": "briefing.wav"},
            created_at=now,
            updated_at=now,
        )


class _IngestionRepo:
    async def create_ingestion_job(self, payload, conn=None):
        self.payload = payload
        self.job_id = uuid4()
        return self.job_id

    async def get_ingestion_job(self, *, workspace_id, job_id, user_id):
        return SimpleNamespace(
            id=job_id,
            document_id=self.payload.document_id,
            status="queued",
            stage="queued",
            attempts=1,
            stats={},
            error_code=None,
            error_message=None,
        )


class _Storage:
    async def create_signed_upload_target(self, *, bucket, path, upsert=False):
        return SimpleNamespace(bucket=bucket, path=path, upload_url="https://example/upload")


class _Connection:
    async def commit(self):
        return None


class _Database:
    @asynccontextmanager
    async def connection(self):
        yield _Connection()


class _Ingestion:
    def __init__(self):
        self.enqueued = []

    async def enqueue_ingestion(self, payload):
        self.enqueued.append(payload)


def test_audio_ingestion_service_creates_audio_upload_target():
    service = AudioIngestionService(
        db=_Database(),
        document_repository=_DocumentRepo(),
        audio_repository=_AudioRepo(),
        ingestion_repository=_IngestionRepo(),
        ingestion_service=_Ingestion(),
        storage=_Storage(),
        settings=Settings(_env_file=None, supabase_raw_bucket="raw-documents", supabase_storage_url="https://example.supabase.co", supabase_storage_service_key="service-role"),
    )

    response = asyncio.run(
        service.create_upload_target(
            uuid4(),
            SimpleNamespace(user_id=uuid4()),
            CreateAudioUploadUrlRequest(filename="briefing.wav", content_type="audio/wav"),
        )
    )

    assert response.bucket == "raw-documents"
    assert response.path.endswith("/raw/briefing.wav")


def test_audio_ingestion_service_reingest_enqueues_job():
    ingestion = _Ingestion()
    doc_repo = _DocumentRepo()
    service = AudioIngestionService(
        db=_Database(),
        document_repository=doc_repo,
        audio_repository=_AudioRepo(),
        ingestion_repository=_IngestionRepo(),
        ingestion_service=ingestion,
        storage=_Storage(),
        settings=Settings(_env_file=None, supabase_storage_url="https://example.supabase.co", supabase_storage_service_key="service-role"),
    )
    document_id = uuid4()

    response = asyncio.run(
        service.reingest_audio_document(
            uuid4(),
            document_id,
            IngestAudioDocumentRequest(force_reindex=True),
            SimpleNamespace(user_id=uuid4()),
        )
    )

    assert response.document_id == document_id
    assert len(ingestion.enqueued) == 1
