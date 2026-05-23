from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AudioDocumentCreateInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: UUID
    document_id: UUID
    audio_bucket: str | None = None
    audio_path: str | None = None
    mime_type: str
    audio_format: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AudioDocumentUpdateInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    audio_bucket: str | None = None
    audio_path: str | None = None
    mime_type: str | None = None
    audio_format: str | None = None
    estimated_duration_ms: int | None = None
    transcript_language: str | None = None
    transcription_provider: str | None = None
    transcription_model: str | None = None
    segment_count: int | None = None
    warning_count: int | None = None
    warnings: list[str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(slots=True)
class AudioDocumentRow:
    id: UUID
    workspace_id: UUID
    document_id: UUID
    audio_bucket: str | None
    audio_path: str | None
    mime_type: str
    audio_format: str
    estimated_duration_ms: int | None
    transcript_language: str | None
    transcription_provider: str | None
    transcription_model: str | None
    segment_count: int
    warning_count: int
    warnings: list[Any]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "AudioDocumentRow":
        return cls(**row)
