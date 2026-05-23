from __future__ import annotations

from uuid import UUID

from app.api.schemas.audio import (
    AudioDocumentDetailResponse,
    AudioDocumentMetadataResponse,
    CreateAudioUploadUrlRequest,
    CreateAudioUploadUrlResponse,
    IngestAudioDocumentRequest,
    IngestionJobResponse,
)
from app.domain.entities.rag import IngestionTaskPayload
from app.storage.models.audio import AudioDocumentCreateInput
from app.storage.models.document import DocumentCreateInput, DocumentStorageUpdateInput
from app.storage.models.ingestion import IngestionJobCreateInput
from app.voice.audio_formats import extension_for_mime_type


class AudioIngestionService:
    def __init__(
        self,
        *,
        document_repository,
        audio_repository,
        ingestion_repository,
        ingestion_service,
        storage,
        settings,
    ) -> None:
        self._document_repository = document_repository
        self._audio_repository = audio_repository
        self._ingestion_repository = ingestion_repository
        self._ingestion_service = ingestion_service
        self._storage = storage
        self._settings = settings

    async def create_upload_target(
        self,
        workspace_id: UUID,
        principal,
        payload: CreateAudioUploadUrlRequest,
    ) -> CreateAudioUploadUrlResponse:
        extension_for_mime_type(payload.content_type)
        title = payload.title or payload.filename
        document_id = await self._document_repository.create_document(
            DocumentCreateInput(
                workspace_id=workspace_id,
                created_by=principal.user_id,
                title=title,
                source_type="audio",
                source_uri=f"storage://{self._settings.supabase_raw_bucket}/{title}",
                storage_bucket=self._settings.supabase_raw_bucket,
                storage_path="pending",
                content_hash=None,
                status="pending",
                sensitivity=payload.sensitivity,
                metadata={
                    **payload.metadata,
                    "_content_type": payload.content_type,
                    "_filename": payload.filename,
                    "audio_mime_type": payload.content_type,
                },
            )
        )
        path = f"workspaces/{workspace_id}/documents/{document_id}/raw/{payload.filename}"
        await self._document_repository.update_document_storage(
            DocumentStorageUpdateInput(
                document_id=document_id,
                source_uri=f"storage://{self._settings.supabase_raw_bucket}/{path}",
                storage_bucket=self._settings.supabase_raw_bucket,
                storage_path=path,
            )
        )
        await self._audio_repository.create_audio_document(
            AudioDocumentCreateInput(
                workspace_id=workspace_id,
                document_id=document_id,
                audio_bucket=self._settings.supabase_raw_bucket,
                audio_path=path,
                mime_type=payload.content_type,
                audio_format=_audio_format(payload.filename, payload.content_type),
                metadata={**payload.metadata, "filename": payload.filename},
            )
        )
        target = await self._storage.create_signed_upload_target(
            bucket=self._settings.supabase_raw_bucket,
            path=path,
        )
        return CreateAudioUploadUrlResponse(
            bucket=target.bucket,
            path=target.path,
            upload_url=_normalize_upload_url(target.upload_url),
            document_id=document_id,
        )

    async def get_audio_document(
        self,
        workspace_id: UUID,
        document_id: UUID,
        principal,
    ) -> AudioDocumentDetailResponse:
        document = await self._document_repository.get_document(
            workspace_id=workspace_id,
            document_id=document_id,
            user_id=principal.user_id,
        )
        audio = await self._audio_repository.get_audio_document(workspace_id=workspace_id, document_id=document_id)
        return AudioDocumentDetailResponse(
            id=document.id,
            title=document.title,
            source_type=document.source_type,
            status=document.status,
            metadata=document.metadata,
            chunk_count=document.chunk_count,
            audio=AudioDocumentMetadataResponse(
                audio_bucket=audio.audio_bucket,
                audio_path=audio.audio_path,
                mime_type=audio.mime_type,
                audio_format=audio.audio_format,
                estimated_duration_ms=audio.estimated_duration_ms,
                transcript_language=audio.transcript_language,
                transcription_provider=audio.transcription_provider,
                transcription_model=audio.transcription_model,
                segment_count=audio.segment_count,
                warning_count=audio.warning_count,
                warnings=list(audio.warnings),
                metadata=dict(audio.metadata),
                created_at=audio.created_at,
                updated_at=audio.updated_at,
            ),
        )

    async def reingest_audio_document(
        self,
        workspace_id: UUID,
        document_id: UUID,
        payload: IngestAudioDocumentRequest,
        principal,
    ) -> IngestionJobResponse:
        await self._document_repository.get_document_source(
            workspace_id=workspace_id,
            document_id=document_id,
            user_id=principal.user_id,
        )
        job_id = await self._ingestion_repository.create_ingestion_job(
            IngestionJobCreateInput(workspace_id=workspace_id, document_id=document_id)
        )
        task_payload = IngestionTaskPayload(
            workspace_id=workspace_id,
            document_id=document_id,
            job_id=job_id,
            force_reindex=payload.force_reindex,
            chunking_version=payload.chunking_version,
            embedding_model=payload.embedding_model,
        )
        await self._ingestion_service.enqueue_ingestion(task_payload)
        row = await self._ingestion_repository.get_ingestion_job(
            workspace_id=workspace_id,
            job_id=job_id,
            user_id=principal.user_id,
        )
        return IngestionJobResponse(
            ingestion_job_id=row.id,
            document_id=row.document_id,
            status=row.status,
            stage=row.stage,
            attempts=row.attempts,
            stats=row.stats,
            error_code=row.error_code,
            error_message=row.error_message,
        )


def _audio_format(filename: str, content_type: str) -> str:
    extension_for_mime_type(content_type)
    lowered = filename.lower()
    if "." in lowered:
        extension = lowered.rsplit(".", 1)[-1]
        if extension in {"wav", "mp3", "webm", "ogg", "m4a", "mp4"}:
            return "m4a" if extension == "mp4" else extension
    return {
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/webm": "webm",
        "audio/ogg": "ogg",
        "audio/mp4": "m4a",
        "audio/x-m4a": "m4a",
    }.get(content_type, "audio")


def _normalize_upload_url(value: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc and parsed.path.startswith("/object/upload/sign/"):
        return parsed._replace(path=f"/storage/v1{parsed.path}").geturl()
    return value
