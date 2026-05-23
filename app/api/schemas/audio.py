from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CreateAudioUploadUrlRequest(BaseModel):
    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    sensitivity: str = Field(default="internal")


class CreateAudioUploadUrlResponse(BaseModel):
    bucket: str
    path: str
    upload_url: str
    document_id: UUID


class IngestAudioDocumentRequest(BaseModel):
    force_reindex: bool = False
    chunking_version: str | None = None
    embedding_model: str | None = None


class AudioDocumentMetadataResponse(BaseModel):
    audio_bucket: str | None = None
    audio_path: str | None = None
    mime_type: str
    audio_format: str
    estimated_duration_ms: int | None = None
    transcript_language: str | None = None
    transcription_provider: str | None = None
    transcription_model: str | None = None
    segment_count: int = 0
    warning_count: int = 0
    warnings: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AudioDocumentDetailResponse(BaseModel):
    id: UUID
    title: str
    source_type: str
    status: str
    metadata: dict[str, Any]
    chunk_count: int
    audio: AudioDocumentMetadataResponse


class IngestionJobResponse(BaseModel):
    ingestion_job_id: UUID
    document_id: UUID
    status: str
    stage: str | None = None
    attempts: int
    stats: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
