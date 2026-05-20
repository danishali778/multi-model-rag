from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class VoiceTurnCreateInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: UUID
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    transcript: str
    transcript_confidence: float | None = None
    input_duration_ms: int | None = None
    output_duration_ms: int | None = None
    stt_provider: str
    stt_model: str
    tts_provider: str | None = None
    tts_model: str | None = None
    input_audio_bucket: str | None = None
    input_audio_path: str | None = None
    output_audio_bucket: str | None = None
    output_audio_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VoiceTurnUpdateInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_audio_bucket: str | None = None
    input_audio_path: str | None = None
    output_audio_bucket: str | None = None
    output_audio_path: str | None = None
    output_duration_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(slots=True)
class VoiceTurnRow:
    id: UUID
    workspace_id: UUID
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    input_audio_bucket: str | None
    input_audio_path: str | None
    output_audio_bucket: str | None
    output_audio_path: str | None
    transcript: str
    transcript_confidence: float | None
    input_duration_ms: int | None
    output_duration_ms: int | None
    stt_provider: str
    stt_model: str
    tts_provider: str | None
    tts_model: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "VoiceTurnRow":
        return cls(**row)
