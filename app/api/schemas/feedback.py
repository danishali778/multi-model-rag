from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class FeedbackCreateRequest(BaseModel):
    rating: int = Field(ge=-1, le=1)
    comment: str | None = None
    categories: list[str] = Field(default_factory=list)


class FeedbackCreateResponse(BaseModel):
    feedback_id: UUID
    status: str
