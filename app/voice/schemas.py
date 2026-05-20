from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class VoiceInputReference:
    bucket: str
    path: str
    mime_type: str
    filename: str


@dataclass(slots=True)
class VoiceOutputArtifact:
    bucket: str
    path: str
    url: str
    format: str
    duration_ms: int | None = None


@dataclass(slots=True)
class VoiceTurnMetadata:
    transcript_confidence: float | None
    input_duration_ms: int | None
    output_duration_ms: int | None
    stt_provider: str
    stt_model: str
    tts_provider: str | None = None
    tts_model: str | None = None
    extra: dict[str, Any] | None = None
