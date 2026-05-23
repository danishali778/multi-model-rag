from __future__ import annotations

from app.domain.entities.rag import ExtractedDocument
from app.ingestion.audio.schemas import AudioParseResult
from app.ingestion.parsers.base import BaseParser


def normalize_audio_parse_result(
    *,
    parser: BaseParser,
    parse_result: AudioParseResult,
    metadata: dict,
) -> ExtractedDocument:
    title = parse_result.title or parser.default_title(metadata)
    section_title = "Audio Transcript"
    section_path = [section_title]
    blocks = []
    order_index = 0
    heading = None
    if parse_result.segments:
        heading = parser.make_block(
            block_type="heading",
            text=section_title,
            order_index=0,
            section_path=section_path,
            heading_level=1,
            parent_block_id=None,
        )
        blocks.append(heading)
        order_index = 1

    for segment in parse_result.segments:
        blocks.append(
            parser.make_block(
                block_type="paragraph",
                text=segment.text,
                order_index=order_index,
                section_path=section_path,
                parent_block_id=heading.id if heading else None,
                metadata={
                    "content_kind": "audio_transcript_segment",
                    "audio_segment_id": f"audio-segment-{segment.segment_index}",
                    "segment_index": segment.segment_index,
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "speaker_label": segment.speaker_label,
                    "segment_confidence": segment.confidence,
                },
            )
        )
        order_index += 1

    document = parser.build_document(
        title=title,
        metadata={
            **metadata,
            "source_type": "audio",
            "parser_backend": parse_result.provider,
            "transcription_provider": parse_result.provider,
            "transcription_model": parse_result.model_name,
            "audio_mime_type": parse_result.mime_type,
            "audio_format": parse_result.audio_format,
            "audio_duration_ms": parse_result.duration_ms,
            "transcript_language": parse_result.language,
            "segment_count": len(parse_result.segments),
        },
        blocks=blocks,
        warnings=parse_result.warnings,
    )
    return document
