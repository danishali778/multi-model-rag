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

    @classmethod
    def from_row(cls, row: dict) -> "ParentContextRow":
        return cls(**row)
