from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.entities.rag import ExtractedBlock
from app.ingestion.chunking import ChunkDraft, StructureEdgeDraft, StructureNodeDraft


class IngestionJobCreateInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID | None = None
    workspace_id: UUID
    document_id: UUID


class IngestionJobUpdateInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    stage: str
    error_code: str | None = None
    error_message: str | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
    attempts: int | None = None


class StageExtractedDocumentInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: UUID
    content_hash: str
    extracted_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    parser_version: str
    processed_storage_bucket: str
    processed_storage_path: str
    should_skip: bool
    chunking_version: str
    embedding_model: str


class ChunkReplacementInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    workspace_id: UUID
    document_id: UUID
    blocks: list[ExtractedBlock]
    nodes: list[StructureNodeDraft] = Field(default_factory=list)
    edges: list[StructureEdgeDraft] = Field(default_factory=list)
    chunks: list[ChunkDraft]
    embeddings: list[list[float]]
    embedding_model: str
    chunking_version: str


@dataclass(slots=True)
class IngestionJobRow:
    id: UUID
    workspace_id: UUID
    document_id: UUID
    status: str
    stage: str
    attempts: int
    stats: dict[str, Any]
    error_code: str | None
    error_message: str | None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict) -> "IngestionJobRow":
        return cls(**row)


@dataclass(slots=True)
class UserIngestionJobRow:
    id: UUID
    document_id: UUID
    status: str
    stage: str
    attempts: int
    error_code: str | None
    error_message: str | None
    stats: dict[str, Any]
    created_at: datetime
    finished_at: datetime | None

    @classmethod
    def from_row(cls, row: dict) -> "UserIngestionJobRow":
        return cls(**row)
