from __future__ import annotations

from app.domain.entities.rag import ExtractedDocument
from app.domain.errors import BadRequestError
from app.ingestion.audio.normalization import normalize_audio_parse_result
from app.ingestion.audio.transcription import transcribe_audio_document
from app.ingestion.parsers.base import BaseParser


class AudioParser(BaseParser):
    source_type = "audio"

    def __init__(self, *, model_router) -> None:
        self._model_router = model_router

    def parse(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        raise BadRequestError("Audio parsing requires asynchronous transcription and must use parse_async().")

    async def parse_async(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        mime_type = str(metadata.get("_content_type") or metadata.get("content_type") or "").strip()
        if not mime_type:
            raise BadRequestError("Audio ingestion requires a content type in document metadata.")
        filename = str(metadata.get("_filename") or metadata.get("filename") or f"audio.{mime_type.rsplit('/', 1)[-1]}")
        title = metadata.get("title") if isinstance(metadata.get("title"), str) else self.default_title(metadata)
        parse_result = await transcribe_audio_document(
            model_router=self._model_router,
            audio_bytes=raw_bytes,
            mime_type=mime_type,
            filename=filename,
            title=title,
        )
        return normalize_audio_parse_result(parser=self, parse_result=parse_result, metadata=metadata)
