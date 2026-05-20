from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.schemas.chat import SourceResponse, UsageResponse


class VoiceChatRequest(BaseModel):
    conversation_id: UUID | None = None
    profile: str | None = None
    document_ids: list[UUID] | None = None
    metadata: dict[str, Any] | None = None
    audio_upload_bucket: str | None = None
    audio_upload_path: str | None = None
    mime_type: str | None = None


class VoiceChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    user_transcript: str
    answer: str
    assistant_audio_url: str | None = None
    sources: list[SourceResponse] = Field(default_factory=list)
    model: str | None = None
    usage: UsageResponse | None = None
    metadata: dict[str, Any] | None = None
