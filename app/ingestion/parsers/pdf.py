from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from app.domain.entities.rag import ExtractedDocument
from app.ingestion.parsers.base import BaseParser


class PdfParser(BaseParser):
    source_type = "pdf"

    def parse(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        reader = PdfReader(BytesIO(raw_bytes))
        pages: list[str] = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        text = "\n\n".join(part.strip() for part in pages if part.strip())
        title = None
        metadata_title = reader.metadata.title if reader.metadata else None
        if metadata_title:
            title = str(metadata_title).strip()
        return ExtractedDocument(
            text=text,
            detected_source_type=self.source_type,
            title=title or self.default_title(metadata),
            metadata={**metadata, "source_type": self.source_type, "page_count": len(reader.pages)},
        )
