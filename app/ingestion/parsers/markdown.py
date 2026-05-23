from __future__ import annotations

from typing import Any
from uuid import uuid4

from markdown_it import MarkdownIt
from markdown_it.token import Token

from app.domain.entities.rag import ExtractedDocument
from app.ingestion.parsers.base import BaseParser
from app.ingestion.parsers.pdf import (
    _format_table_row,
    _looks_like_algorithm_step,
    _looks_like_equation_explanation,
    _match_algorithm_label,
    _match_equation_label,
    _match_figure_caption,
    _match_table_caption,
    _normalize_whitespace,
)
from app.ingestion.parsers.structured_markup import _extract_explicit_equation_text


class MarkdownParser(BaseParser):
    source_type = "markdown"

    def parse(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        text = raw_bytes.decode("utf-8")
        tokens = MarkdownIt("commonmark").enable("table").parse(text)
        blocks = []
        warnings: list[str] = []
        order_index = 0
        section_path: list[str] = []
        heading_ids: list[Any] = []
        list_depth = 0
        blockquote_depth = 0
        pending_equation_id: str | None = None
        pending_algorithm_id: str | None = None
        pending_algorithm_label: str | None = None
        pending_table_caption: str | None = None
        table_counter = 0
        index = 0

        def current_parent_id():
            return heading_ids[-1] if heading_ids else None

        def clear_pending(*, equation: bool = True, algorithm: bool = True) -> None:
            nonlocal pending_equation_id, pending_algorithm_id, pending_algorithm_label
            if equation:
                pending_equation_id = None
            if algorithm:
                pending_algorithm_id = None
                pending_algorithm_label = None

        def emit_block(
            block_type: str,
            content: str,
            *,
            heading_level: int | None = None,
            metadata_block: dict[str, Any] | None = None,
        ) -> None:
            nonlocal order_index
            normalized = content.strip() if block_type == "heading" else _normalize_whitespace(content)
            if not normalized:
                return
            block = self.make_block(
                block_type=block_type,
                text=normalized,
                order_index=order_index,
                section_path=section_path,
                heading_level=heading_level,
                parent_block_id=current_parent_id(),
                metadata=metadata_block,
            )
            blocks.append(block)
            order_index += 1

        def emit_paragraph(content: str, *, metadata_block: dict[str, Any] | None = None) -> None:
            emit_block("paragraph", content, metadata_block=metadata_block)
            clear_pending(algorithm=True)

        def emit_equation(content: str) -> None:
            nonlocal pending_equation_id
            equation_id = str(uuid4())
            emit_block(
                "equation",
                content,
                metadata_block={
                    "content_kind": "equation",
                    "equation_id": equation_id,
                    "equation_label": _match_equation_label(_normalize_whitespace(content)),
                },
            )
            pending_equation_id = equation_id
            clear_pending(algorithm=True)

        def emit_equation_explanation(content: str) -> None:
            nonlocal pending_equation_id
            if pending_equation_id is None:
                emit_paragraph(content)
                return
            emit_block(
                "equation_explanation",
                content,
                metadata_block={
                    "content_kind": "equation_explanation",
                    "equation_id": pending_equation_id,
                },
            )
            pending_equation_id = None

        def emit_algorithm(content: str, *, algorithm_id: str | None = None) -> None:
            nonlocal pending_algorithm_id, pending_algorithm_label
            algorithm_id = algorithm_id or str(uuid4())
            pending_algorithm_label = pending_algorithm_label or _match_algorithm_label(content) or "Algorithm"
            emit_block(
                "algorithm",
                content,
                metadata_block={
                    "content_kind": "algorithm",
                    "algorithm_id": algorithm_id,
                    "algorithm_label": pending_algorithm_label,
                },
            )
            pending_algorithm_id = algorithm_id
            clear_pending(equation=True, algorithm=False)

        def emit_special_or_paragraph(content: str, *, metadata_block: dict[str, Any] | None = None) -> None:
            normalized = _normalize_whitespace(content)
            if not normalized:
                return
            if pending_equation_id and _looks_like_equation_explanation(normalized):
                emit_equation_explanation(normalized)
                return
            explicit_equation = _extract_explicit_equation_text(normalized)
            if explicit_equation:
                emit_equation(explicit_equation)
                return
            if pending_algorithm_id and _looks_like_algorithm_step(normalized):
                emit_algorithm(normalized, algorithm_id=pending_algorithm_id)
                return
            if _match_algorithm_label(normalized):
                emit_algorithm(normalized)
                return
            if _match_figure_caption(normalized):
                emit_block(
                    "figure_caption",
                    normalized,
                    metadata_block={
                        "content_kind": "figure_caption",
                        "caption_label": _match_figure_caption(normalized) or "Figure",
                        **(metadata_block or {}),
                    },
                )
                clear_pending()
                return
            emit_paragraph(normalized, metadata_block=metadata_block)
            clear_pending(equation=True, algorithm=False)

        def next_significant_token_type(start_index: int) -> str | None:
            for lookahead in range(start_index, len(tokens)):
                token_type = tokens[lookahead].type
                if token_type.endswith("_close"):
                    continue
                if token_type == "inline":
                    continue
                return token_type
            return None

        while index < len(tokens):
            token = tokens[index]

            if token.type in {"bullet_list_open", "ordered_list_open"}:
                list_depth += 1
                index += 1
                continue
            if token.type in {"bullet_list_close", "ordered_list_close"}:
                list_depth = max(0, list_depth - 1)
                index += 1
                continue
            if token.type == "blockquote_open":
                blockquote_depth += 1
                index += 1
                continue
            if token.type == "blockquote_close":
                blockquote_depth = max(0, blockquote_depth - 1)
                index += 1
                continue

            if token.type == "heading_open":
                inline = tokens[index + 1]
                level = int(token.tag[1]) if token.tag.startswith("h") else 1
                heading_text = _normalize_whitespace(inline.content)
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
                clear_pending()
                pending_table_caption = None
                index += 3
                continue

            if token.type == "paragraph_open":
                inline = tokens[index + 1]
                paragraph_text = _normalize_whitespace(inline.content)
                metadata_block: dict[str, Any] = {}
                if list_depth:
                    metadata_block["list_depth"] = max(0, list_depth - 1)
                if blockquote_depth:
                    metadata_block["blockquote_depth"] = blockquote_depth
                if list_depth:
                    emit_block("list_item", paragraph_text, metadata_block=metadata_block)
                    if pending_algorithm_id and _looks_like_algorithm_step(paragraph_text):
                        blocks.pop()
                        order_index -= 1
                        emit_algorithm(paragraph_text, algorithm_id=pending_algorithm_id)
                    else:
                        clear_pending(equation=True, algorithm=False)
                else:
                    if _match_table_caption(paragraph_text) and next_significant_token_type(index + 3) == "table_open":
                        pending_table_caption = paragraph_text
                        clear_pending()
                        index += 3
                        continue
                    emit_special_or_paragraph(paragraph_text, metadata_block=metadata_block or None)
                index += 3
                continue

            if token.type == "fence":
                emit_paragraph(
                    token.content.rstrip(),
                    metadata_block={
                        "content_kind": "code_block",
                        "code_language": token.info.strip() or None,
                    },
                )
                pending_table_caption = None
                clear_pending()
                index += 1
                continue

            if token.type == "table_open":
                table_id = f"markdown-table-{table_counter}"
                table_counter += 1
                headers: list[str] = []
                rows: list[list[str]] = []
                table_index = index + 1
                while table_index < len(tokens) and tokens[table_index].type != "table_close":
                    current = tokens[table_index]
                    if current.type == "tr_open":
                        cells: list[str] = []
                        row_index = table_index + 1
                        while row_index < len(tokens) and tokens[row_index].type != "tr_close":
                            if tokens[row_index].type == "inline":
                                cells.append(_normalize_whitespace(tokens[row_index].content))
                            row_index += 1
                        if not headers:
                            headers = cells
                        else:
                            rows.append(cells)
                    table_index += 1

                parse_status = "row_backed" if rows else "caption_only"
                caption_text = pending_table_caption
                caption_label = _match_table_caption(caption_text or "") or ("Table" if caption_text else None)
                if caption_text:
                    emit_block(
                        "table_caption",
                        caption_text,
                        metadata_block={
                            "content_kind": "table_caption",
                            "table_id": table_id,
                            "caption_label": caption_label or "Table",
                            "table_parse_status": parse_status,
                            "table_headers": headers,
                        },
                    )
                for row_number, row in enumerate(rows):
                    row_text = _format_table_row(headers, row)
                    if not row_text:
                        continue
                    emit_block(
                        "table_row",
                        row_text,
                        metadata_block={
                            "content_kind": "table_row",
                            "table_id": table_id,
                            "caption_label": caption_label,
                            "table_headers": headers,
                            "row_index": row_number,
                            "table_parse_status": "row_backed",
                        },
                    )
                pending_table_caption = None
                clear_pending()
                index = table_index + 1
                continue

            index += 1

        if any(token.type == "fence" for token in tokens) and text.count("```") % 2 == 1:
            warnings.append("Markdown code fence was not closed; trailing content was treated as code.")

        title = next((block.text for block in blocks if block.block_type == "heading"), None)
        return self.build_document(title=title, metadata=metadata, blocks=blocks, warnings=warnings)
