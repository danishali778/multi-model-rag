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
        body = root.find(".//w:body", _WORD_NAMESPACE)
        blocks = []
        section_path: list[str] = []
        heading_ids: list = []
        order_index = 0

        def current_parent_id():
            return heading_ids[-1] if heading_ids else None

        def paragraph_text(paragraph) -> str:
            text_nodes = [node.text for node in paragraph.findall(".//w:t", _WORD_NAMESPACE) if node.text]
            return "".join(text_nodes).strip()

        def paragraph_style(paragraph) -> str | None:
            style = paragraph.find("./w:pPr/w:pStyle", _WORD_NAMESPACE)
            if style is None:
                return None
            return style.attrib.get(f"{{{_WORD_NAMESPACE['w']}}}val")

        def is_list_paragraph(paragraph) -> bool:
            return paragraph.find("./w:pPr/w:numPr", _WORD_NAMESPACE) is not None

        if body is None:
            return self.build_document(title=self.default_title(metadata), metadata=metadata, blocks=[])

        for child in list(body):
            tag = child.tag.rsplit('}', 1)[-1]
            if tag == 'p':
                text = paragraph_text(child)
                if not text:
                    continue
                style = paragraph_style(child) or ""
                lower_style = style.lower()
                if lower_style.startswith("heading"):
                    digits = ''.join(ch for ch in lower_style if ch.isdigit())
                    level = int(digits) if digits else 1
                    section_path = section_path[: level - 1] + [text]
                    heading_ids[:] = heading_ids[: level - 1]
                    block = self.make_block(
                        block_type="heading",
                        text=text,
                        order_index=order_index,
                        section_path=section_path,
                        heading_level=level,
                        parent_block_id=heading_ids[-1] if heading_ids else None,
                    )
                    blocks.append(block)
                    heading_ids.append(block.id)
                    order_index += 1
                    continue
                if is_list_paragraph(child) or "list" in lower_style:
                    block_type = "list_item"
                    metadata_block = {"style": style or None}
                else:
                    block_type = "paragraph"
                    metadata_block = {"style": style or None}
                block = self.make_block(
                    block_type=block_type,
                    text=text,
                    order_index=order_index,
                    section_path=section_path,
                    parent_block_id=current_parent_id(),
                    metadata=metadata_block,
                )
                blocks.append(block)
                order_index += 1
            elif tag == 'tbl':
                rows = []
                for row in child.findall('.//w:tr', _WORD_NAMESPACE):
                    cells = []
                    for cell in row.findall('./w:tc', _WORD_NAMESPACE):
                        cell_text = ''.join(node.text for node in cell.findall('.//w:t', _WORD_NAMESPACE) if node.text).strip()
                        cells.append(cell_text)
                    if any(cells):
                        rows.append(' | '.join(cells))
                if rows:
                    block = self.make_block(
                        block_type='table',
                        text='\n'.join(rows),
                        order_index=order_index,
                        section_path=section_path,
                        parent_block_id=current_parent_id(),
                        metadata={'row_count': len(rows)},
                    )
                    blocks.append(block)
                    order_index += 1

        title = next((block.text for block in blocks if block.block_type == 'heading'), None)
        if not title and blocks:
            title = blocks[0].text[:120]
        return self.build_document(title=title, metadata={**metadata, 'paragraph_count': len([b for b in blocks if b.block_type in {'paragraph', 'list_item'}])}, blocks=blocks)
