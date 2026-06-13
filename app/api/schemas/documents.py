from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


InlineDocumentSourceType = Literal["text"]
UploadDocumentSourceType = Literal["markdown", "pdf", "docx", "html", "audio"]


class CreateDocumentRequest(BaseModel):
    title: str = Field(min_length=1)
    source_type: InlineDocumentSourceType = Field(default="text")
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
    source_type: UploadDocumentSourceType | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    sensitivity: str = Field(default="internal")

    @model_validator(mode="after")
    def validate_source_type_matches_upload(self) -> "CreateUploadUrlRequest":
        inferred = _infer_upload_source_type(self.filename, self.content_type)
        if self.source_type is not None and self.source_type != inferred:
            raise ValueError(
                f"source_type '{self.source_type}' does not match upload content type '{self.content_type}'."
            )
        return self


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


def _infer_upload_source_type(filename: str, content_type: str) -> UploadDocumentSourceType:
    lowered = filename.lower()
    if lowered.endswith(".md") or content_type == "text/markdown":
        return "markdown"
    if lowered.endswith(".pdf") or content_type == "application/pdf":
        return "pdf"
    if lowered.endswith(".docx") or content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return "docx"
    if lowered.endswith(".html") or lowered.endswith(".htm") or content_type == "text/html":
        return "html"
    if lowered.endswith((".wav", ".mp3", ".webm", ".ogg", ".m4a", ".mp4")) or content_type in {
        "audio/wav",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp3",
        "audio/webm",
        "audio/ogg",
        "audio/mp4",
        "audio/x-m4a",
    }:
        return "audio"
    raise ValueError(f"Unsupported upload content type '{content_type}'.")
