from __future__ import annotations

from app.domain.entities.rag import ExtractedDocument
from app.ingestion.parsers.base import BaseParser
from app.ingestion.parsers.structured_markup import StructuredMarkupNormalizer


class HtmlParser(BaseParser):
    source_type = "html"

    def parse(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        html = raw_bytes.decode("utf-8", errors="ignore")
        normalizer = StructuredMarkupNormalizer(self, parser_backend="beautifulsoup-lxml")
        return normalizer.parse_html(html=html, metadata=metadata)
