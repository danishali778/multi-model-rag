from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class AudioTranscriptSegment:
    segment_index: int
    text: str
    start_ms: int | None
    end_ms: int | None
    speaker_label: str | None = None
    confidence: float | None = None


@dataclass(slots=True)
class AudioParseResult:
    transcript: str
    title: str | None
    provider: str
    model_name: str
    mime_type: str
    filename: str
    audio_format: str
    duration_ms: int | None = None
    language: str | None = None
    segments: list[AudioTranscriptSegment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AudioIngestionArtifact:
    bucket: str
    path: str
    mime_type: str
    audio_format: str
    duration_ms: int | None = None
