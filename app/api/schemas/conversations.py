from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ConversationListItem(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    items: list[ConversationListItem]


class MessageListItem(BaseModel):
    id: UUID
    role: str
    content: str
    model_profile: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    token_usage: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ConversationDetailResponse(BaseModel):
    conversation_id: UUID
    items: list[MessageListItem]
