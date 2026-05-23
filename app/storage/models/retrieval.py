from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(slots=True)
class RetrievalCandidateRow:
    id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    metadata: dict[str, Any]
    title: str
    sensitivity: str
    parent_block_id: UUID | None = None
    page_number: int | None = None
    chunk_type: str | None = None
    section_title: str | None = None
    subsection_title: str | None = None
    section_path: list[str] | None = None
    vector_score: float | None = None
    fts_score: float | None = None
    node_id: UUID | None = None
    parent_node_id: UUID | None = None
    previous_chunk_id: UUID | None = None
    next_chunk_id: UUID | None = None
    level: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    chunking_version: str | None = None

    @classmethod
    def from_row(cls, row: dict) -> "RetrievalCandidateRow":
        return cls(**row)


@dataclass(slots=True)
class ParentContextRow:
    parent_block_id: UUID
    content: str
    page_number: int | None
    chunk_type: str | None
    section_title: str | None
    subsection_title: str | None
    section_path: list[str] | None
    node_id: UUID | None = None
    parent_node_id: UUID | None = None
    level: int | None = None
    page_start: int | None = None
    page_end: int | None = None

    @classmethod
    def from_row(cls, row: dict) -> "ParentContextRow":
        return cls(**row)


@dataclass(slots=True)
class StructureNodeRow:
    id: UUID
    document_id: UUID
    node_type: str
    node_key: str
    title: str | None
    section_path: list[str] | None
    level: int | None
    page_start: int | None
    page_end: int | None
    block_order_start: int
    block_order_end: int
    parent_node_id: UUID | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_row(cls, row: dict) -> "StructureNodeRow":
        return cls(**row)
