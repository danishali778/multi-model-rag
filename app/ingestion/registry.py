from __future__ import annotations

from app.domain.entities.rag import ExtractedDocument
from app.domain.errors import BadRequestError
from app.ingestion.parsers import DocxParser, HtmlParser, MarkdownParser, PdfParser


class ParserRegistry:
    def __init__(self):
        self.parsers = {
            "markdown": MarkdownParser(),
            "md": MarkdownParser(),
            "pdf": PdfParser(),
            "docx": DocxParser(),
            "html": HtmlParser(),
            "htm": HtmlParser(),
        }

    def parse(self, *, source_type: str, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        parser = self.parsers.get(source_type.lower())
        if parser is None:
            raise BadRequestError(f"Unsupported source type '{source_type}'.")
        return parser.parse(raw_bytes, metadata)
