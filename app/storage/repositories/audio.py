from __future__ import annotations

import json
from uuid import UUID

from app.core.config import Settings
from app.domain.errors import NotFoundError
from app.storage.db.session import Database
from app.storage.models.audio import AudioDocumentCreateInput, AudioDocumentRow, AudioDocumentUpdateInput


class AudioRepository:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def create_audio_document(self, payload: AudioDocumentCreateInput, *, conn=None) -> None:
        query = """
            insert into audio_documents (
                workspace_id, document_id, audio_bucket, audio_path, mime_type, audio_format, metadata
            )
            values (%s, %s, %s, %s, %s, %s, %s::jsonb)
            on conflict (document_id) do update
            set audio_bucket = excluded.audio_bucket,
                audio_path = excluded.audio_path,
                mime_type = excluded.mime_type,
                audio_format = excluded.audio_format,
                metadata = coalesce(audio_documents.metadata, '{}'::jsonb) || excluded.metadata,
                updated_at = now()
        """
        if conn is None:
            async with self.db.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        query,
                        (
                            payload.workspace_id,
                            payload.document_id,
                            payload.audio_bucket,
                            payload.audio_path,
                            payload.mime_type,
                            payload.audio_format,
                            json.dumps(payload.metadata),
                        ),
                    )
                    await conn.commit()
            return
        async with conn.cursor() as cur:
            await cur.execute(
                query,
                (
                    payload.workspace_id,
                    payload.document_id,
                    payload.audio_bucket,
                    payload.audio_path,
                    payload.mime_type,
                    payload.audio_format,
                    json.dumps(payload.metadata),
                ),
            )

    async def update_audio_document(self, *, document_id: UUID, payload: AudioDocumentUpdateInput) -> None:
        query = """
            update audio_documents
            set audio_bucket = coalesce(%s, audio_bucket),
                audio_path = coalesce(%s, audio_path),
                mime_type = coalesce(%s, mime_type),
                audio_format = coalesce(%s, audio_format),
                estimated_duration_ms = coalesce(%s, estimated_duration_ms),
                transcript_language = coalesce(%s, transcript_language),
                transcription_provider = coalesce(%s, transcription_provider),
                transcription_model = coalesce(%s, transcription_model),
                segment_count = coalesce(%s, segment_count),
                warning_count = coalesce(%s, warning_count),
                warnings = coalesce(%s::jsonb, warnings),
                metadata = coalesce(metadata, '{}'::jsonb) || %s::jsonb,
                updated_at = now()
            where document_id = %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        payload.audio_bucket,
                        payload.audio_path,
                        payload.mime_type,
                        payload.audio_format,
                        payload.estimated_duration_ms,
                        payload.transcript_language,
                        payload.transcription_provider,
                        payload.transcription_model,
                        payload.segment_count,
                        payload.warning_count,
                        json.dumps(payload.warnings) if payload.warnings is not None else None,
                        json.dumps(payload.metadata),
                        document_id,
                    ),
                )
                await conn.commit()

    async def get_audio_document(self, *, workspace_id: UUID, document_id: UUID) -> AudioDocumentRow:
        query = """
            select *
            from audio_documents
            where workspace_id = %s and document_id = %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, document_id))
                row = await cur.fetchone()
        if not row:
            raise NotFoundError("Audio document metadata not found.")
        return AudioDocumentRow.from_row(row)
