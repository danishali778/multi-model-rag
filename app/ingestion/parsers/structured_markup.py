from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from bs4 import BeautifulSoup, NavigableString, Tag

from app.domain.entities.rag import ExtractedBlock, ExtractedDocument
from app.ingestion.parsers.base import BaseParser
from app.ingestion.parsers.pdf import (
    _format_table_row,
    _looks_like_algorithm_step,
    _looks_like_equation_explanation,
    _looks_like_equation_text,
    _match_algorithm_label,
    _match_equation_label,
    _match_figure_caption,
    _match_table_caption,
    _normalize_whitespace,
)

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_CONTAINER_TAGS = {"article", "section", "main", "div", "body", "header"}
_IGNORED_TAGS = {"script", "style", "noscript", "svg", "canvas"}
_BLOCKQUOTE_TAGS = {"blockquote"}
_CODE_TAGS = {"pre", "code"}
_TABLE_HINT_CLASSES = {"table", "data-table"}
_EQUATION_HINT_CLASSES = {"equation", "formula", "math", "math-display"}
_ALGORITHM_HINT_CLASSES = {"algorithm", "procedure"}


@dataclass(slots=True)
class TableGroup:
    caption_text: str | None
    headers: list[str]
    rows: list[list[str]]


@dataclass(slots=True)
class _ParserState:
    section_path: list[str]
    heading_ids: list[Any]
    blocks: list[ExtractedBlock]
    warnings: list[str]
    order_index: int = 0
    pending_equation_id: str | None = None
    pending_algorithm_id: str | None = None
    pending_algorithm_label: str | None = None


class StructuredMarkupNormalizer:
    def __init__(self, parser: BaseParser, *, parser_backend: str) -> None:
        self._parser = parser
        self._parser_backend = parser_backend

    def parse_html(
        self,
        *,
        html: str,
        metadata: dict[str, Any],
        title_override: str | None = None,
        extra_warnings: list[str] | None = None,
    ) -> ExtractedDocument:
        soup = BeautifulSoup(html, "lxml")
        root = soup.body or soup
        state = _ParserState(section_path=[], heading_ids=[], blocks=[], warnings=list(extra_warnings or []))
        self._walk_children(root, state=state, list_depth=0, blockquote_depth=0)

        title = title_override
        if title is None and soup.title and soup.title.string:
            title = _normalize_whitespace(soup.title.string)
        if title is None:
            first_heading = next((block.text for block in state.blocks if block.block_type == "heading"), None)
            title = first_heading or self._parser.default_title(metadata)

        document = self._parser.build_document(
            title=title,
            metadata={**metadata, "parser_backend": self._parser_backend},
            blocks=state.blocks,
            warnings=state.warnings,
        )
        return document

    def _walk_children(
        self,
        node: Tag,
        *,
        state: _ParserState,
        list_depth: int,
        blockquote_depth: int,
    ) -> None:
        children = [child for child in node.children if self._is_meaningful_child(child)]
        index = 0
        while index < len(children):
            child = children[index]
            if isinstance(child, NavigableString):
                index += 1
                continue

            name = (child.name or "").lower()
            if name in _IGNORED_TAGS or self._is_hidden(child):
                index += 1
                continue

            next_index, next_tag = self._next_tag(children, index + 1)

            if name in _HEADING_TAGS:
                self._emit_heading(_normalize_whitespace(child.get_text(" ", strip=True)), int(name[1]), state=state)
                index += 1
                continue

            if name in {"ul", "ol"}:
                self._emit_list(child, state=state, depth=list_depth, blockquote_depth=blockquote_depth)
                index += 1
                continue

            if name in _BLOCKQUOTE_TAGS:
                self._walk_children(child, state=state, list_depth=list_depth, blockquote_depth=blockquote_depth + 1)
                self._clear_pending_context(state)
                index += 1
                continue

            if name == "figure":
                self._emit_figure(child, state=state)
                index += 1
                continue

            if name == "table":
                self._emit_table(child, state=state, caption_text=None)
                index += 1
                continue

            if name in _CODE_TAGS:
                self._emit_code_block(child.get_text("\n", strip=True), state=state)
                index += 1
                continue

            if self._looks_like_explicit_equation_tag(child):
                self._emit_equation(_normalize_whitespace(child.get_text(" ", strip=True)), state=state)
                index += 1
                continue

            text = _normalize_whitespace(child.get_text(" ", strip=True))
            if not text:
                if name in _CONTAINER_TAGS:
                    self._walk_children(child, state=state, list_depth=list_depth, blockquote_depth=blockquote_depth)
                index += 1
                continue

            if next_tag is not None and next_tag.name and next_tag.name.lower() == "table" and _match_table_caption(text):
                self._emit_table(next_tag, state=state, caption_text=text)
                index = next_index + 1
                continue

            if name in _CONTAINER_TAGS and not self._should_treat_container_as_paragraph(child):
                self._walk_children(child, state=state, list_depth=list_depth, blockquote_depth=blockquote_depth)
                index += 1
                continue

            if self._emit_special_text_block(
                text,
                state=state,
                metadata={
                    "blockquote_depth": blockquote_depth,
                }
                if blockquote_depth
                else None,
                source_tag=child,
            ):
                index += 1
                continue

            self._emit_paragraph(
                text,
                state=state,
                metadata={"blockquote_depth": blockquote_depth} if blockquote_depth else None,
            )
            index += 1

    def _emit_heading(self, text: str, level: int, *, state: _ParserState) -> None:
        if not text:
            return
        state.section_path[:] = state.section_path[: level - 1] + [text]
        state.heading_ids[:] = state.heading_ids[: level - 1]
        block = self._parser.make_block(
            block_type="heading",
            text=text,
            order_index=state.order_index,
            section_path=state.section_path,
            heading_level=level,
            parent_block_id=state.heading_ids[-1] if state.heading_ids else None,
        )
        state.blocks.append(block)
        state.heading_ids.append(block.id)
        state.order_index += 1
        self._clear_pending_context(state)

    def _emit_paragraph(
        self,
        text: str,
        *,
        state: _ParserState,
        metadata: dict[str, Any] | None = None,
        block_type: str = "paragraph",
    ) -> None:
        normalized = _normalize_whitespace(text)
        if not normalized:
            return
        block = self._parser.make_block(
            block_type=block_type,
            text=normalized,
            order_index=state.order_index,
            section_path=state.section_path,
            parent_block_id=state.heading_ids[-1] if state.heading_ids else None,
            metadata=metadata,
        )
        state.blocks.append(block)
        state.order_index += 1
        if block_type == "paragraph":
            state.pending_algorithm_id = None
            state.pending_algorithm_label = None
        if block_type != "equation_explanation":
            state.pending_equation_id = None

    def _emit_list(self, node: Tag, *, state: _ParserState, depth: int, blockquote_depth: int) -> None:
        for position, item in enumerate(node.find_all("li", recursive=False), start=1):
            item_text = _extract_list_item_text(item)
            metadata = {"list_depth": depth, "list_index": position}
            if blockquote_depth:
                metadata["blockquote_depth"] = blockquote_depth
            if item_text:
                if not self._emit_special_text_block(item_text, state=state, metadata=metadata, source_tag=item):
                    block = self._parser.make_block(
                        block_type="list_item",
                        text=item_text,
                        order_index=state.order_index,
                        section_path=state.section_path,
                        parent_block_id=state.heading_ids[-1] if state.heading_ids else None,
                        metadata=metadata,
                    )
                    state.blocks.append(block)
                    state.order_index += 1
            for child_list in item.find_all(["ul", "ol"], recursive=False):
                self._emit_list(child_list, state=state, depth=depth + 1, blockquote_depth=blockquote_depth)

    def _emit_code_block(self, text: str, *, state: _ParserState, language: str | None = None) -> None:
        metadata: dict[str, Any] = {"content_kind": "code_block"}
        if language:
            metadata["code_language"] = language
        self._emit_paragraph(text, state=state, metadata=metadata)

    def _emit_table(self, table: Tag, *, state: _ParserState, caption_text: str | None) -> None:
        group = _extract_table_group(table, explicit_caption=caption_text)
        blocks, next_order_index = _build_table_blocks(
            parser=self._parser,
            order_index=state.order_index,
            section_path=state.section_path,
            parent_block_id=state.heading_ids[-1] if state.heading_ids else None,
            group=group,
        )
        state.blocks.extend(blocks)
        state.order_index = next_order_index
        self._clear_pending_context(state)

    def _emit_figure(self, figure: Tag, *, state: _ParserState) -> None:
        figcaption = figure.find("figcaption")
        caption_text = _normalize_whitespace(figcaption.get_text(" ", strip=True)) if figcaption else ""
        if caption_text:
            block = self._parser.make_block(
                block_type="figure_caption",
                text=caption_text,
                order_index=state.order_index,
                section_path=state.section_path,
                parent_block_id=state.heading_ids[-1] if state.heading_ids else None,
                metadata={
                    "content_kind": "figure_caption",
                    "caption_label": _match_figure_caption(caption_text) or "Figure",
                    "related_caption_id": str(uuid4()),
                },
            )
            state.blocks.append(block)
            state.order_index += 1
        self._clear_pending_context(state)

    def _emit_equation(self, text: str, *, state: _ParserState) -> None:
        normalized = _normalize_whitespace(text)
        if not normalized:
            return
        equation_id = str(uuid4())
        label = _match_equation_label(normalized)
        block = self._parser.make_block(
            block_type="equation",
            text=normalized,
            order_index=state.order_index,
            section_path=state.section_path,
            parent_block_id=state.heading_ids[-1] if state.heading_ids else None,
            metadata={
                "content_kind": "equation",
                "equation_id": equation_id,
                "equation_label": label,
            },
        )
        state.blocks.append(block)
        state.order_index += 1
        state.pending_equation_id = equation_id
        state.pending_algorithm_id = None
        state.pending_algorithm_label = None

    def _emit_equation_explanation(self, text: str, *, state: _ParserState) -> None:
        if not state.pending_equation_id:
            self._emit_paragraph(text, state=state)
            return
        block = self._parser.make_block(
            block_type="equation_explanation",
            text=text,
            order_index=state.order_index,
            section_path=state.section_path,
            parent_block_id=state.heading_ids[-1] if state.heading_ids else None,
            metadata={
                "content_kind": "equation_explanation",
                "equation_id": state.pending_equation_id,
            },
        )
        state.blocks.append(block)
        state.order_index += 1
        state.pending_equation_id = None

    def _emit_algorithm(self, text: str, *, state: _ParserState, algorithm_id: str | None = None) -> None:
        normalized = _normalize_whitespace(text)
        if not normalized:
            return
        algorithm_id = algorithm_id or str(uuid4())
        algorithm_label = state.pending_algorithm_label or _match_algorithm_label(normalized) or "Algorithm"
        block = self._parser.make_block(
            block_type="algorithm",
            text=normalized,
            order_index=state.order_index,
            section_path=state.section_path,
            parent_block_id=state.heading_ids[-1] if state.heading_ids else None,
            metadata={
                "content_kind": "algorithm",
                "algorithm_id": algorithm_id,
                "algorithm_label": algorithm_label,
            },
        )
        state.blocks.append(block)
        state.order_index += 1
        state.pending_algorithm_id = algorithm_id
        state.pending_algorithm_label = algorithm_label
        state.pending_equation_id = None

    def _emit_special_text_block(
        self,
        text: str,
        *,
        state: _ParserState,
        metadata: dict[str, Any] | None,
        source_tag: Tag | None,
    ) -> bool:
        normalized = _normalize_whitespace(text)
        if not normalized:
            return False
        if state.pending_equation_id and _looks_like_equation_explanation(normalized):
            self._emit_equation_explanation(normalized, state=state)
            return True
        explicit_equation = _extract_explicit_equation_text(normalized)
        if explicit_equation:
            self._emit_equation(explicit_equation, state=state)
            return True
        if self._looks_like_explicit_equation_tag(source_tag) and _looks_like_equation_text(normalized):
            self._emit_equation(normalized, state=state)
            return True
        if state.pending_algorithm_id and _looks_like_algorithm_step(normalized):
            self._emit_algorithm(normalized, state=state, algorithm_id=state.pending_algorithm_id)
            return True
        if _match_algorithm_label(normalized):
            self._emit_algorithm(normalized, state=state)
            return True
        if _match_figure_caption(normalized):
            block = self._parser.make_block(
                block_type="figure_caption",
                text=normalized,
                order_index=state.order_index,
                section_path=state.section_path,
                parent_block_id=state.heading_ids[-1] if state.heading_ids else None,
                metadata={
                    "content_kind": "figure_caption",
                    "caption_label": _match_figure_caption(normalized) or "Figure",
                    **(metadata or {}),
                },
            )
            state.blocks.append(block)
            state.order_index += 1
            self._clear_pending_context(state)
            return True
        return False

    def _looks_like_explicit_equation_tag(self, tag: Tag | None) -> bool:
        if tag is None:
            return False
        name = (tag.name or "").lower()
        if name == "math":
            return True
        classes = {value.lower() for value in tag.get("class", []) if isinstance(value, str)}
        return bool(classes & _EQUATION_HINT_CLASSES)

    def _should_treat_container_as_paragraph(self, tag: Tag) -> bool:
        classes = {value.lower() for value in tag.get("class", []) if isinstance(value, str)}
        if classes & (_EQUATION_HINT_CLASSES | _ALGORITHM_HINT_CLASSES | _TABLE_HINT_CLASSES):
            return True
        return False

    def _next_tag(self, children: list[Any], start: int) -> tuple[int, Tag | None]:
        for index in range(start, len(children)):
            child = children[index]
            if isinstance(child, Tag) and self._is_meaningful_child(child):
                return index, child
        return -1, None

    def _clear_pending_context(self, state: _ParserState) -> None:
        state.pending_equation_id = None
        state.pending_algorithm_id = None
        state.pending_algorithm_label = None

    def _is_meaningful_child(self, child: Any) -> bool:
        if isinstance(child, NavigableString):
            return bool(_normalize_whitespace(str(child)))
        if not isinstance(child, Tag):
            return False
        return True

    def _is_hidden(self, child: Tag) -> bool:
        hidden = child.get("hidden")
        if hidden is not None:
            return True
        aria_hidden = str(child.get("aria-hidden", "")).lower()
        if aria_hidden == "true":
            return True
        style = str(child.get("style", "")).lower()
        return "display:none" in style or "visibility:hidden" in style


def _extract_table_group(table: Tag, *, explicit_caption: str | None = None) -> TableGroup:
    caption = explicit_caption
    if caption is None:
        caption_tag = table.find("caption", recursive=False)
        if caption_tag is not None:
            caption = _normalize_whitespace(caption_tag.get_text(" ", strip=True))

    headers: list[str] = []
    rows: list[list[str]] = []
    direct_rows = table.find_all("tr")
    if not direct_rows:
        return TableGroup(caption_text=caption, headers=headers, rows=rows)

    first_row_cells: list[str] | None = None
    first_row_is_header = False

    for row_index, row in enumerate(direct_rows):
        header_cells = row.find_all("th")
        data_cells = row.find_all("td")
        cells = header_cells or data_cells
        cell_values = [_normalize_whitespace(cell.get_text(" ", strip=True)) for cell in cells]
        cell_values = [value for value in cell_values if value]
        if not cell_values:
            continue
        if row_index == 0:
            first_row_cells = cell_values
            first_row_is_header = bool(header_cells) or row.find_parent("thead") is not None
            if first_row_is_header:
                headers = cell_values
                continue
        rows.append(cell_values)

    if not headers and first_row_cells and len(rows) >= 1:
        headers = first_row_cells
        if rows and rows[0] == headers:
            rows = rows[1:]

    return TableGroup(caption_text=caption, headers=headers, rows=rows)


def _build_table_blocks(
    *,
    parser: BaseParser,
    order_index: int,
    section_path: list[str],
    parent_block_id: Any | None,
    group: TableGroup,
) -> tuple[list[ExtractedBlock], int]:
    table_id = str(uuid4())
    blocks: list[ExtractedBlock] = []
    headers = [_normalize_whitespace(header) for header in group.headers if _normalize_whitespace(header)]
    parse_status = "row_backed" if group.rows else "caption_only"
    caption_label = _match_table_caption(group.caption_text or "") or ("Table" if group.caption_text else None)

    if group.caption_text:
        blocks.append(
            parser.make_block(
                block_type="table_caption",
                text=group.caption_text,
                order_index=order_index,
                section_path=section_path,
                parent_block_id=parent_block_id,
                metadata={
                    "content_kind": "table_caption",
                    "table_id": table_id,
                    "caption_label": caption_label or "Table",
                    "table_parse_status": parse_status,
                    "table_headers": headers,
                },
            )
        )
        order_index += 1

    for row_index, row in enumerate(group.rows):
        row_text = _format_table_row(headers, row)
        if not row_text:
            continue
        blocks.append(
            parser.make_block(
                block_type="table_row",
                text=row_text,
                order_index=order_index,
                section_path=section_path,
                parent_block_id=parent_block_id,
                metadata={
                    "content_kind": "table_row",
                    "table_id": table_id,
                    "caption_label": caption_label,
                    "table_headers": headers,
                    "row_index": row_index,
                    "table_parse_status": "row_backed",
                },
            )
        )
        order_index += 1

    return blocks, order_index


def _extract_explicit_equation_text(text: str) -> str | None:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return None
    for prefix, suffix in (("$$", "$$"), ("\\[", "\\]")):
        if normalized.startswith(prefix) and normalized.endswith(suffix):
            inner = _normalize_whitespace(normalized[len(prefix) : -len(suffix)])
            return inner or None
    return None


def _extract_list_item_text(item: Tag) -> str:
    parts: list[str] = []
    for child in item.children:
        if isinstance(child, NavigableString):
            text = _normalize_whitespace(str(child))
            if text:
                parts.append(text)
            continue
        if not isinstance(child, Tag):
            continue
        if child.name and child.name.lower() in {"ul", "ol"}:
            continue
        text = _normalize_whitespace(child.get_text(" ", strip=True))
        if text:
            parts.append(text)
    return _normalize_whitespace(" ".join(parts))
