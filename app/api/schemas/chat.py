from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    conversation_id: UUID | None = None
    model_profile: str = Field(default="balanced")
    top_k: int = Field(default=5, ge=1, le=20)
    filters: dict[str, Any] = Field(default_factory=dict)
    stream: bool = False


class ModelResponse(BaseModel):
    profile: str
    provider: str
    name: str


class SourceResponse(BaseModel):
    source_id: int
    document_id: UUID
    chunk_id: UUID
    title: str
    score: float
    snippet: str


class UsageResponse(BaseModel):
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    answer: str
    model: ModelResponse
    sources: list[SourceResponse]
    usage: UsageResponse
