from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentCreateInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: UUID
    created_by: UUID
    title: str
    source_type: str
    source_uri: str
    storage_bucket: str | None = None
    storage_path: str | None = None
    content_hash: str | None = None
    status: str
    sensitivity: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentStorageUpdateInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: UUID
    source_uri: str
    storage_bucket: str
    storage_path: str


class DocumentMetadataUpdateInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: UUID
    metadata_updates: dict[str, Any] = Field(default_factory=dict)
    status: str | None = None


@dataclass(slots=True)
class DocumentListRow:
    id: UUID
    title: str
    source_type: str
    status: str
    sensitivity: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "DocumentListRow":
        return cls(**row)


@dataclass(slots=True)
class DocumentDetailRow:
    id: UUID
    title: str
    source_type: str
    status: str
    metadata: dict[str, Any]
    chunk_count: int

    @classmethod
    def from_row(cls, row: dict) -> "DocumentDetailRow":
        return cls(**row)


@dataclass(slots=True)
class DocumentSourceRow:
    id: UUID
    title: str
    source_type: str
    sensitivity: str
    metadata: dict[str, Any]

    @classmethod
    def from_row(cls, row: dict) -> "DocumentSourceRow":
        return cls(**row)


@dataclass(slots=True)
class DocumentIngestionRow:
    id: UUID
    workspace_id: UUID
    title: str
    source_type: str
    source_uri: str | None
    storage_bucket: str | None
    storage_path: str | None
    content_hash: str | None
    status: str
    sensitivity: str
    metadata: dict[str, Any]

    @classmethod
    def from_row(cls, row: dict) -> "DocumentIngestionRow":
        return cls(**row)
