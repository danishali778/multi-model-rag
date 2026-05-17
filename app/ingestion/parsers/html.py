from __future__ import annotations

from bs4 import BeautifulSoup

from app.domain.entities.rag import ExtractedDocument
from app.ingestion.parsers.base import BaseParser


class HtmlParser(BaseParser):
    source_type = "html"

    def parse(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        html = raw_bytes.decode("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else self.default_title(metadata)
        text = soup.get_text(separator=" ", strip=True)
        return ExtractedDocument(
            text=text,
            detected_source_type=self.source_type,
            title=title,
            metadata={**metadata, "source_type": self.source_type},
        )
