from __future__ import annotations

from app.ingestion.audio.schemas import AudioParseResult
from app.ingestion.audio.segmentation import build_audio_segments
from app.llm.providers.base import TranscriptionResult
from app.voice.audio_formats import extension_for_mime_type


async def transcribe_audio_document(
    *,
    model_router,
    audio_bytes: bytes,
    mime_type: str,
    filename: str,
    title: str | None,
) -> AudioParseResult:
    transcription: TranscriptionResult = await model_router.transcribe_audio(
        audio_bytes=audio_bytes,
        mime_type=mime_type,
        filename=filename,
    )
    segments, warnings = build_audio_segments(
        transcript=transcription.transcript,
        segments=transcription.segments,
        duration_ms=transcription.input_duration_ms,
    )
    return AudioParseResult(
        transcript=transcription.transcript.strip(),
        title=title,
        provider=transcription.provider,
        model_name=transcription.model_name,
        mime_type=mime_type,
        filename=filename,
        audio_format=extension_for_mime_type(mime_type),
        duration_ms=transcription.input_duration_ms,
        language=transcription.language,
        segments=segments,
        warnings=warnings,
    )
