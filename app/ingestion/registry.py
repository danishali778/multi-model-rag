from __future__ import annotations

from app.ingestion.audio.parser import AudioParser
from app.domain.entities.rag import ExtractedDocument
from app.domain.errors import BadRequestError
from app.ingestion.parsers import DocxParser, HtmlParser, MarkdownParser, PdfParser


class ParserRegistry:
    def __init__(self, *, model_router):
        # Future LaTeX support is intentionally deferred; when added, use `tex` with a plasTeX-backed parser.
        self.parsers = {
            "audio": AudioParser(model_router=model_router),
            "markdown": MarkdownParser(),
            "md": MarkdownParser(),
            "pdf": PdfParser(),
            "docx": DocxParser(),
            "html": HtmlParser(),
            "htm": HtmlParser(),
        }

    async def parse(self, *, source_type: str, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        parser = self.parsers.get(source_type.lower())
        if parser is None:
            raise BadRequestError(f"Unsupported source type '{source_type}'.")
        return await parser.parse_async(raw_bytes, metadata)
