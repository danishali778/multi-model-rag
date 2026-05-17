from __future__ import annotations

import re

from app.domain.entities.rag import ExtractedDocument
from app.ingestion.parsers.base import BaseParser


class MarkdownParser(BaseParser):
    source_type = "markdown"

    def parse(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        text = raw_bytes.decode("utf-8")
        title = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip() or None
                if title:
                    break
        normalized = _strip_markdown(text).strip()
        return ExtractedDocument(
            text=normalized,
            detected_source_type=self.source_type,
            title=title or self.default_title(metadata),
            metadata={**metadata, "source_type": self.source_type},
        )


def _strip_markdown(text: str) -> str:
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"!\[.*?\]\(.*?\)", " ", cleaned)
    cleaned = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", cleaned)
    cleaned = re.sub(r"[*_>#-]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned)
