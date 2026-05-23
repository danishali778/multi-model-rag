from __future__ import annotations

from app.ingestion.audio.schemas import AudioTranscriptSegment


def build_audio_segments(
    *,
    transcript: str,
    segments: list[dict],
    duration_ms: int | None,
) -> tuple[list[AudioTranscriptSegment], list[str]]:
    warnings: list[str] = []
    built: list[AudioTranscriptSegment] = []

    for index, raw_segment in enumerate(segments):
        text = str(raw_segment.get("text", "")).strip()
        if not text:
            continue
        start_ms = _to_ms(raw_segment.get("start"))
        end_ms = _to_ms(raw_segment.get("end"))
        if start_ms is None or end_ms is None:
            warnings.append("One or more transcription segments were missing timestamps.")
        built.append(
            AudioTranscriptSegment(
                segment_index=index,
                text=text,
                start_ms=start_ms,
                end_ms=end_ms,
                speaker_label=raw_segment.get("speaker"),
                confidence=_to_confidence(raw_segment.get("avg_logprob")),
            )
        )

    if built:
        return built, warnings

    normalized_transcript = transcript.strip()
    if not normalized_transcript:
        warnings.append("Transcription returned empty transcript content.")
        return [], warnings

    warnings.append("Transcription returned no explicit segments; a single fallback transcript segment was created.")
    return [
        AudioTranscriptSegment(
            segment_index=0,
            text=normalized_transcript,
            start_ms=0 if duration_ms is not None else None,
            end_ms=duration_ms,
        )
    ], warnings


def _to_ms(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value) * 1000)
    except (TypeError, ValueError):
        return None


def _to_confidence(value: object) -> float | None:
    if value is None:
        return None
    try:
        # OpenAI returns avg_logprob; convert to a monotonic confidence proxy for metadata only.
        return round(max(0.0, min(1.0, 1.0 + float(value) / 10.0)), 4)
    except (TypeError, ValueError):
        return None
