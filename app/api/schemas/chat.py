from __future__ import annotations

from typing import Literal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


ChatProfile = Literal["fast", "balanced", "reasoning", "local"]


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    conversation_id: UUID | None = None
    profile: ChatProfile | None = None
    document_ids: list[UUID] | None = None
    metadata: dict[str, Any] | None = None


class SourceResponse(BaseModel):
    chunk_id: UUID | None = None
    document_id: UUID
    document_name: str
    snippet: str
    score: float | None = None
    section_title: str | None = None
    subsection_title: str | None = None
    section_path: list[str] | None = None
    page_number: int | None = None
    chunk_type: str | None = None


class UsageResponse(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    answer: str
    sources: list[SourceResponse] = Field(default_factory=list)
    model: str | None = None
    usage: UsageResponse | None = None
    metadata: dict[str, Any] | None = None
