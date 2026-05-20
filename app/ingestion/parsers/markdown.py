from __future__ import annotations

import re

from app.domain.entities.rag import ExtractedDocument
from app.ingestion.parsers.base import BaseParser


class MarkdownParser(BaseParser):
    source_type = "markdown"

    def parse(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        text = raw_bytes.decode("utf-8")
        lines = text.splitlines()
        blocks = []
        warnings: list[str] = []
        order_index = 0
        section_path: list[str] = []
        heading_ids: list = []
        paragraph_lines: list[str] = []
        code_lines: list[str] = []
        table_lines: list[str] = []
        in_code = False

        def current_parent_id():
            return heading_ids[-1] if heading_ids else None

        def flush_paragraph() -> None:
            nonlocal order_index, paragraph_lines
            if not paragraph_lines:
                return
            block = self.make_block(
                block_type="paragraph",
                text=" ".join(line.strip() for line in paragraph_lines if line.strip()),
                order_index=order_index,
                section_path=section_path,
                parent_block_id=current_parent_id(),
            )
            blocks.append(block)
            order_index += 1
            paragraph_lines = []

        def flush_table() -> None:
            nonlocal order_index, table_lines
            if not table_lines:
                return
            rows = [" | ".join(cell.strip() for cell in line.strip().strip("|").split("|")) for line in table_lines if line.strip()]
            block = self.make_block(
                block_type="table",
                text="\n".join(rows),
                order_index=order_index,
                section_path=section_path,
                parent_block_id=current_parent_id(),
                metadata={"row_count": len(rows)},
            )
            blocks.append(block)
            order_index += 1
            table_lines = []

        def flush_code() -> None:
            nonlocal order_index, code_lines
            if not code_lines:
                return
            block = self.make_block(
                block_type="code",
                text="\n".join(code_lines),
                order_index=order_index,
                section_path=section_path,
                parent_block_id=current_parent_id(),
            )
            blocks.append(block)
            order_index += 1
            code_lines = []

        for line in lines:
            stripped = line.rstrip()
            heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
            list_match = re.match(r"^(\s*)([-*+] |\d+[.)] )(.*)$", stripped)
            is_table_line = stripped.strip().startswith("|") and stripped.strip().endswith("|") and stripped.count("|") >= 2
            fence = stripped.strip().startswith("```")

            if fence:
                flush_paragraph()
                flush_table()
                if in_code:
                    flush_code()
                    in_code = False
                else:
                    in_code = True
                continue

            if in_code:
                code_lines.append(stripped)
                continue

            if heading_match:
                flush_paragraph()
                flush_table()
                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()
                section_path = section_path[: level - 1] + [heading_text]
                heading_ids[:] = heading_ids[: level - 1]
                block = self.make_block(
                    block_type="heading",
                    text=heading_text,
                    order_index=order_index,
                    section_path=section_path,
                    heading_level=level,
                    parent_block_id=heading_ids[-1] if heading_ids else None,
                )
                blocks.append(block)
                heading_ids.append(block.id)
                order_index += 1
                continue

            if is_table_line:
                flush_paragraph()
                table_lines.append(stripped)
                continue
            else:
                flush_table()

            if not stripped.strip():
                flush_paragraph()
                continue

            if list_match:
                flush_paragraph()
                depth = max(0, len(list_match.group(1)) // 2)
                item_text = list_match.group(3).strip()
                block = self.make_block(
                    block_type="list_item",
                    text=item_text,
                    order_index=order_index,
                    section_path=section_path,
                    parent_block_id=current_parent_id(),
                    metadata={"list_depth": depth},
                )
                blocks.append(block)
                order_index += 1
                continue

            paragraph_lines.append(stripped)

        if in_code:
            warnings.append("Markdown code fence was not closed; trailing content was treated as code.")
        flush_paragraph()
        flush_table()
        flush_code()

        title = next((block.text for block in blocks if block.block_type == "heading"), None)
        return self.build_document(title=title, metadata=metadata, blocks=blocks, warnings=warnings)
