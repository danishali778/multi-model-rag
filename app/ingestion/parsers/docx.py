from __future__ import annotations

from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

from app.domain.entities.rag import ExtractedDocument
from app.ingestion.parsers.base import BaseParser

_WORD_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


class DocxParser(BaseParser):
    source_type = "docx"

    def parse(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        with ZipFile(BytesIO(raw_bytes)) as archive:
            xml_data = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml_data)
        paragraphs = []
        for paragraph in root.findall(".//w:p", _WORD_NAMESPACE):
            text_nodes = [node.text for node in paragraph.findall(".//w:t", _WORD_NAMESPACE) if node.text]
            if text_nodes:
                paragraphs.append("".join(text_nodes))
        title = paragraphs[0][:120] if paragraphs else self.default_title(metadata)
        return ExtractedDocument(
            text="\n\n".join(paragraphs).strip(),
            detected_source_type=self.source_type,
            title=title or self.default_title(metadata),
            metadata={**metadata, "source_type": self.source_type, "paragraph_count": len(paragraphs)},
        )
