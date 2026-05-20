from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class CreateDocumentRequest(BaseModel):
    title: str = Field(min_length=1)
    source_type: str = Field(default="text")
    text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    sensitivity: str = Field(default="internal")


class CreateDocumentResponse(BaseModel):
    document_id: UUID
    status: str
    ingestion_job_id: UUID


class CreateUploadUrlRequest(BaseModel):
    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    title: str | None = None
    source_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    sensitivity: str = Field(default="internal")


class CreateUploadUrlResponse(BaseModel):
    bucket: str
    path: str
    upload_url: str
    document_id: UUID

    @field_validator("upload_url")
    @classmethod
    def normalize_supabase_signed_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme and parsed.netloc and parsed.path.startswith("/object/upload/sign/"):
            return parsed._replace(path=f"/storage/v1{parsed.path}").geturl()
        return value


class IngestDocumentRequest(BaseModel):
    force_reindex: bool = False
    chunking_version: str | None = None
    embedding_model: str | None = None


class DocumentListItem(BaseModel):
    id: UUID
    title: str
    source_type: str
    status: str
    sensitivity: str
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentListItem]
    next_cursor: str | None = None


class DocumentDetailResponse(BaseModel):
    id: UUID
    title: str
    source_type: str
    status: str
    metadata: dict[str, Any]
    chunk_count: int


class IngestionJobResponse(BaseModel):
    ingestion_job_id: UUID
    document_id: UUID
    status: str
    stage: str | None = None
    attempts: int
    stats: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


class IngestionJobListItem(BaseModel):
    id: UUID
    document_id: UUID
    status: str
    stage: str | None = None
    attempts: int
    stats: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class IngestionJobListResponse(BaseModel):
    items: list[IngestionJobListItem]
