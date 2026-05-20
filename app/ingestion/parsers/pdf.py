from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from app.domain.entities.rag import ExtractedDocument
from app.ingestion.parsers.base import BaseParser


class PdfParser(BaseParser):
    source_type = "pdf"

    def parse(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        reader = PdfReader(BytesIO(raw_bytes))
        blocks = []
        warnings: list[str] = []
        section_path: list[str] = []
        heading_ids: list = []
        order_index = 0

        def current_parent_id():
            return heading_ids[-1] if heading_ids else None

        def flush_paragraph(lines: list[str], page_number: int):
            nonlocal order_index
            text = ' '.join(part.strip() for part in lines if part.strip()).strip()
            if not text:
                return
            block = self.make_block(
                block_type='paragraph',
                text=text,
                order_index=order_index,
                section_path=section_path,
                page_number=page_number,
                parent_block_id=current_parent_id(),
            )
            blocks.append(block)
            order_index += 1

        for page_number, page in enumerate(reader.pages, start=1):
            extracted = page.extract_text() or ''
            lines = [line.strip() for line in extracted.splitlines()]
            paragraph_lines: list[str] = []
            for line in lines:
                if not line:
                    flush_paragraph(paragraph_lines, page_number)
                    paragraph_lines = []
                    continue
                if _looks_like_heading(line):
                    flush_paragraph(paragraph_lines, page_number)
                    paragraph_lines = []
                    heading_text = line.strip()
                    section_path = [heading_text]
                    heading_ids.clear()
                    block = self.make_block(
                        block_type='heading',
                        text=heading_text,
                        order_index=order_index,
                        section_path=section_path,
                        heading_level=1,
                        page_number=page_number,
                    )
                    blocks.append(block)
                    heading_ids.append(block.id)
                    order_index += 1
                    continue
                paragraph_lines.append(line)
            flush_paragraph(paragraph_lines, page_number)
            if not extracted.strip():
                warnings.append(f'Page {page_number} did not yield extractable text.')

        title = None
        metadata_title = reader.metadata.title if reader.metadata else None
        if metadata_title:
            title = str(metadata_title).strip()
        if not title:
            title = next((block.text for block in blocks if block.block_type == 'heading'), None)
        return self.build_document(title=title, metadata={**metadata, 'page_count': len(reader.pages)}, blocks=blocks, warnings=warnings)


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < 4 or len(stripped) > 120:
        return False
    if stripped.endswith(('.', ';', '?', '!')):
        return False
    alpha_chars = [char for char in stripped if char.isalpha()]
    if not alpha_chars:
        return False
    uppercase_ratio = sum(1 for char in alpha_chars if char.isupper()) / len(alpha_chars)
    title_case = stripped == stripped.title()
    return uppercase_ratio > 0.8 or title_case
