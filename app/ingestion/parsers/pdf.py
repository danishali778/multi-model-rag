from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable
from uuid import uuid4

from app.domain.entities.rag import ExtractedDocument
from app.ingestion.parsers.base import BaseParser


@dataclass(slots=True)
class DoclingNormalizedItem:
    kind: str
    text: str
    page_number: int | None = None
    heading_level: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DoclingParseResult:
    title: str | None
    page_count: int
    items: list[DoclingNormalizedItem]
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class _ConvertedItems:
    items: list[DoclingNormalizedItem] = field(default_factory=list)
    title: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _ParseState:
    phase: str = "front_matter"
    saw_body_heading: bool = False
    in_references: bool = False
    abstract_heading_emitted: bool = False


@dataclass(slots=True)
class _TableCaptionGroup:
    index: int
    table_id: str
    page_number: int | None
    section_context: tuple[str, ...]
    caption_label: str | None


class _DoclingAdapter:
    def convert_pdf(self, raw_bytes: bytes) -> DoclingParseResult:
        converter = self._load_converter()
        temp_path: Path | None = None
        try:
            with NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                temp_file.write(raw_bytes)
                temp_path = Path(temp_file.name)
            conversion_result = converter.convert(str(temp_path))
            document = getattr(conversion_result, "document", conversion_result)
            return self._normalize_document(document)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _load_converter(self):
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:  # pragma: no cover - exercised in runtime environments
            raise RuntimeError(
                "Docling is required for PDF parsing. Install the 'docling' dependency."
            ) from exc
        return DocumentConverter()

    def _normalize_document(self, document: Any) -> DoclingParseResult:
        title = self._extract_document_title(document)
        warnings: list[str] = []
        items: list[DoclingNormalizedItem] = []
        page_count = self._extract_page_count(document)
        state = _ParseState()
        pending_equation_id: str | None = None
        pending_algorithm_id: str | None = None
        pending_algorithm_label: str | None = None

        for raw_item, nesting_level in self._iter_document_items(document):
            converted = self._convert_item(raw_item, nesting_level, state=state, document_title=title)
            if converted.title and not title:
                title = converted.title
            warnings.extend(converted.warnings)
            for item in converted.items:
                if item.kind == "heading" and _is_structural_section_heading(item.text):
                    state.phase = "body"
                    state.saw_body_heading = True
                    state.in_references = item.text.strip().upper() == "REFERENCES"
                elif item.kind == "heading" and item.text.strip().lower() == "abstract":
                    state.phase = "abstract"
                    state.abstract_heading_emitted = True
                if (
                    item.kind == "paragraph"
                    and pending_equation_id is not None
                    and _looks_like_equation_explanation(item.text)
                ):
                    item = DoclingNormalizedItem(
                        kind="equation_explanation",
                        text=item.text,
                        page_number=item.page_number,
                        metadata={
                            **item.metadata,
                            "content_kind": "equation_explanation",
                            "equation_id": pending_equation_id,
                            "detection_confidence": "high",
                        },
                    )
                    pending_equation_id = None
                elif (
                    item.kind == "paragraph"
                    and pending_algorithm_id is not None
                    and _looks_like_algorithm_step(item.text)
                ):
                    item = DoclingNormalizedItem(
                        kind="algorithm",
                        text=item.text,
                        page_number=item.page_number,
                        metadata={
                            **item.metadata,
                            "content_kind": "algorithm",
                            "algorithm_id": pending_algorithm_id,
                            "algorithm_label": pending_algorithm_label,
                            "detection_confidence": "medium",
                        },
                    )
                elif item.kind not in {"paragraph", "equation_explanation"}:
                    pending_equation_id = None

                if item.kind == "equation":
                    pending_equation_id = str(item.metadata.get("equation_id", "")) or None
                if item.kind == "algorithm":
                    pending_algorithm_id = str(item.metadata.get("algorithm_id", "")) or None
                    pending_algorithm_label = item.metadata.get("algorithm_label")
                elif item.kind not in {"paragraph", "equation_explanation"}:
                    pending_algorithm_id = None
                    pending_algorithm_label = None
                items.append(item)

        items, post_warnings, stats = self._postprocess_items(items, title=title)
        warnings.extend(post_warnings)

        if page_count == 0:
            page_count = max((item.page_number or 0 for item in items), default=0)
        if not items:
            warnings.append("Docling returned no parseable items for the PDF.")
        return DoclingParseResult(title=title, page_count=page_count, items=items, warnings=warnings, stats=stats)

    def _postprocess_items(
        self,
        items: list[DoclingNormalizedItem],
        *,
        title: str | None,
    ) -> tuple[list[DoclingNormalizedItem], list[str], dict[str, int]]:
        warnings: list[str] = []
        stats = {
            "page_artifact_suppressed_count": 0,
            "decimal_subsection_heading_count": 0,
            "merged_equation_fragment_count": 0,
            "equation_fragment_orphan_count": 0,
            "multi_page_table_header_reuse_count": 0,
        }
        processed = list(items)
        processed = self._suppress_title_heading(processed, title=title)
        processed, suppressed_count = self._suppress_page_artifacts(processed, title=title)
        stats["page_artifact_suppressed_count"] += suppressed_count
        processed = self._normalize_front_matter(processed)
        processed, _promoted_count = self._promote_subsection_headings(processed)
        processed, table_warnings = self._reconcile_table_groups(processed)
        warnings.extend(table_warnings)
        processed, header_reuse_count = self._normalize_table_continuations(processed)
        stats["multi_page_table_header_reuse_count"] += header_reuse_count
        processed, merged_equation_count, orphan_count = self._reconcile_equations(processed)
        stats["merged_equation_fragment_count"] += merged_equation_count
        stats["equation_fragment_orphan_count"] += orphan_count
        stats["decimal_subsection_heading_count"] = _count_promoted_decimal_subsections(processed)
        return processed, warnings, stats

    def _suppress_title_heading(
        self,
        items: list[DoclingNormalizedItem],
        *,
        title: str | None,
    ) -> list[DoclingNormalizedItem]:
        if not title:
            return items
        normalized_title = _normalize_whitespace(title)
        filtered: list[DoclingNormalizedItem] = []
        skipped = False
        for item in items:
            if (
                not skipped
                and item.kind == "heading"
                and item.page_number in {None, 1}
                and _normalize_whitespace(item.text) == normalized_title
            ):
                skipped = True
                continue
            filtered.append(item)
        return filtered

    def _normalize_front_matter(self, items: list[DoclingNormalizedItem]) -> list[DoclingNormalizedItem]:
        first_body_index = next(
            (
                index
                for index, item in enumerate(items)
                if item.kind == "heading" and _is_structural_section_heading(item.text)
            ),
            len(items),
        )
        normalized = list(items)
        for index, item in enumerate(normalized[:first_body_index]):
            if item.kind != "paragraph":
                continue
            if self._should_be_front_matter(item, normalized, index, first_body_index):
                normalized[index] = _as_front_matter_item(item)
        return self._merge_front_matter_continuations(normalized)

    def _should_be_front_matter(
        self,
        item: DoclingNormalizedItem,
        items: list[DoclingNormalizedItem],
        index: int,
        first_body_index: int,
    ) -> bool:
        if item.metadata.get("content_kind") == "front_matter":
            return True
        if item.page_number not in {None, 1}:
            return False
        if _looks_like_front_matter_text(item.text):
            return True
        previous_item = items[index - 1] if index > 0 else None
        if previous_item and previous_item.kind == "paragraph":
            previous_kind = previous_item.metadata.get("content_kind")
            if previous_kind == "front_matter" and _is_front_matter_continuation(previous_item.text, item.text):
                return True
        next_item = items[index + 1] if index + 1 < first_body_index else None
        if (
            next_item
            and next_item.kind == "paragraph"
            and next_item.metadata.get("content_kind") == "front_matter"
            and _is_front_matter_continuation(item.text, next_item.text)
        ):
            return True
        return False

    def _merge_front_matter_continuations(
        self,
        items: list[DoclingNormalizedItem],
    ) -> list[DoclingNormalizedItem]:
        merged: list[DoclingNormalizedItem] = []
        for item in items:
            if (
                merged
                and item.kind == "paragraph"
                and merged[-1].kind == "paragraph"
                and item.metadata.get("content_kind") == "front_matter"
                and merged[-1].metadata.get("content_kind") == "front_matter"
                and item.page_number == merged[-1].page_number
                and _is_front_matter_continuation(merged[-1].text, item.text)
            ):
                merged[-1] = DoclingNormalizedItem(
                    kind="paragraph",
                    text=_normalize_whitespace(f"{merged[-1].text} {item.text}"),
                    page_number=merged[-1].page_number,
                    metadata={**merged[-1].metadata, **item.metadata},
                )
                continue
            merged.append(item)
        return merged

    def _suppress_page_artifacts(
        self,
        items: list[DoclingNormalizedItem],
        *,
        title: str | None,
    ) -> tuple[list[DoclingNormalizedItem], int]:
        title_tokens = _tokenize_title_tokens(title)
        kept: list[DoclingNormalizedItem] = []
        suppressed_count = 0
        index = 0

        while index < len(items):
            item = items[index]
            if item.kind != "paragraph" or item.metadata.get("content_kind") == "front_matter":
                kept.append(item)
                index += 1
                continue

            run_end = index
            run: list[DoclingNormalizedItem] = []
            while (
                run_end < len(items)
                and items[run_end].kind == "paragraph"
                and items[run_end].metadata.get("content_kind") != "front_matter"
                and _looks_like_page_artifact_line(items[run_end].text, title_tokens=title_tokens)
            ):
                run.append(items[run_end])
                run_end += 1

            if run and _is_suppressible_artifact_run(run, title_tokens=title_tokens):
                suppressed_count += len(run)
                index = run_end
                continue

            kept.append(item)
            index += 1

        return kept, suppressed_count

    def _promote_subsection_headings(
        self,
        items: list[DoclingNormalizedItem],
    ) -> tuple[list[DoclingNormalizedItem], int]:
        promoted = 0
        normalized: list[DoclingNormalizedItem] = []
        body_started = False

        for item in items:
            if item.kind == "heading" and _is_structural_section_heading(item.text):
                body_started = True
                normalized.append(item)
                continue

            if body_started and item.kind == "paragraph" and _should_promote_decimal_heading(item.text):
                match = _DECIMAL_SUBSECTION_RE.match(item.text)
                heading_level = _decimal_heading_level(match.group(1)) if match else 2
                normalized.append(
                    DoclingNormalizedItem(
                        kind="heading",
                        text=item.text,
                        page_number=item.page_number,
                        heading_level=heading_level,
                        metadata={
                            **item.metadata,
                            "content_kind": "heading",
                            "normalization_promoted_decimal_subsection": True,
                        },
                    )
                )
                promoted += 1
                continue

            normalized.append(item)

        return normalized, promoted

    def _reconcile_table_groups(
        self,
        items: list[DoclingNormalizedItem],
    ) -> tuple[list[DoclingNormalizedItem], list[str]]:
        warnings: list[str] = []
        contexts = self._section_contexts(items)
        captions: list[_TableCaptionGroup] = []
        caption_by_id: dict[str, _TableCaptionGroup] = {}

        for index, item in enumerate(items):
            if item.kind != "table_caption":
                continue
            table_id = str(item.metadata.get("table_id") or uuid4())
            caption = _TableCaptionGroup(
                index=index,
                table_id=table_id,
                page_number=item.page_number,
                section_context=contexts[index],
                caption_label=_normalize_caption_label(item.metadata.get("caption_label")),
            )
            captions.append(caption)
            caption_by_id[table_id] = caption

        assigned_rows: dict[str, int] = {caption.table_id: 0 for caption in captions}
        reconciled: list[DoclingNormalizedItem] = []

        for index, item in enumerate(items):
            if item.kind == "table_caption":
                table_id = str(item.metadata.get("table_id") or "")
                caption = caption_by_id.get(table_id)
                parse_status = "caption_only"
                if caption and assigned_rows.get(caption.table_id, 0) > 0:
                    parse_status = "row_backed"
                reconciled.append(
                    DoclingNormalizedItem(
                        kind=item.kind,
                        text=item.text,
                        page_number=item.page_number,
                        heading_level=item.heading_level,
                        metadata={
                            **item.metadata,
                            "table_id": caption.table_id if caption else table_id or str(uuid4()),
                            "caption_label": caption.caption_label or item.metadata.get("caption_label"),
                            "table_parse_status": parse_status,
                        },
                    )
                )
                continue

            if item.kind != "table_row":
                reconciled.append(item)
                continue

            existing_table_id = str(item.metadata.get("table_id") or "")
            caption = caption_by_id.get(existing_table_id)
            if caption is None:
                caption = self._find_best_caption_for_row(
                    row_index=index,
                    row=item,
                    captions=captions,
                    row_context=contexts[index],
                )

            if caption is None:
                warnings.append(
                    f"Unassigned table row on page {item.page_number or 'unknown'} could not be matched to a caption."
                )
                reconciled.append(
                    DoclingNormalizedItem(
                        kind="table_row",
                        text=item.text,
                        page_number=item.page_number,
                        metadata={
                            **item.metadata,
                            "table_parse_status": "unassigned_row",
                        },
                    )
                )
                continue

            assigned_rows[caption.table_id] = assigned_rows.get(caption.table_id, 0) + 1
            reconciled.append(
                DoclingNormalizedItem(
                    kind="table_row",
                    text=item.text,
                    page_number=item.page_number,
                    metadata={
                        **item.metadata,
                        "table_id": caption.table_id,
                        "caption_label": caption.caption_label or item.metadata.get("caption_label"),
                        "table_parse_status": "row_backed",
                    },
                )
            )

        finalized: list[DoclingNormalizedItem] = []
        for item in reconciled:
            if item.kind != "table_caption":
                finalized.append(item)
                continue
            row_count = assigned_rows.get(str(item.metadata.get("table_id") or ""), 0)
            parse_status = "row_backed" if row_count else "caption_only"
            if parse_status == "caption_only":
                caption_label = item.metadata.get("caption_label") or "Table"
                warnings.append(f"Table caption '{caption_label}' had no recoverable table rows.")
            finalized.append(
                DoclingNormalizedItem(
                    kind=item.kind,
                    text=item.text,
                    page_number=item.page_number,
                    heading_level=item.heading_level,
                    metadata={
                        **item.metadata,
                        "table_parse_status": parse_status,
                    },
                )
            )

        deduped_warnings = list(dict.fromkeys(warnings))
        return finalized, deduped_warnings

    def _normalize_table_continuations(
        self,
        items: list[DoclingNormalizedItem],
    ) -> tuple[list[DoclingNormalizedItem], int]:
        known_headers: dict[str, list[str]] = {}
        reused_count = 0
        normalized: list[DoclingNormalizedItem] = []

        for item in items:
            if item.kind != "table_row":
                normalized.append(item)
                continue

            metadata = dict(item.metadata)
            table_id = str(metadata.get("table_id") or "")
            item_headers = _usable_table_headers(metadata.get("table_headers") or [])
            if item_headers:
                known_headers[table_id] = item_headers
            headers = item_headers or known_headers.get(table_id, [])

            text = item.text
            if headers and _row_uses_positional_fields(text):
                values = _parse_positional_row_values(text)
                if len(values) == len(headers):
                    text = _format_table_pairs(headers, values)
                    metadata["table_headers"] = headers
                    metadata["reused_table_headers"] = True
                    reused_count += 1
            elif headers and not metadata.get("table_headers"):
                raw_values = [part.strip() for part in text.split("|") if _normalize_whitespace(part)]
                if len(raw_values) == len(headers):
                    text = _format_table_pairs(headers, raw_values)
                    metadata["table_headers"] = headers
                    metadata["reused_table_headers"] = True
                    reused_count += 1

            normalized.append(
                DoclingNormalizedItem(
                    kind=item.kind,
                    text=text,
                    page_number=item.page_number,
                    heading_level=item.heading_level,
                    metadata=metadata,
                )
            )

        return normalized, reused_count

    def _reconcile_equations(
        self,
        items: list[DoclingNormalizedItem],
    ) -> tuple[list[DoclingNormalizedItem], int, int]:
        contexts = self._section_contexts(items)
        merged_count = 0
        orphan_count = 0
        reconciled: list[DoclingNormalizedItem] = []
        index = 0

        while index < len(items):
            item = items[index]
            if item.kind != "equation":
                reconciled.append(item)
                index += 1
                continue

            equation = item
            fragments_merged = 0
            next_index = index + 1

            while next_index < len(items):
                candidate = items[next_index]
                if candidate.kind not in {"equation", "paragraph"}:
                    break
                if not _same_section_context(contexts[index], contexts[next_index]):
                    break
                if not _same_or_continuation_page(equation.page_number, candidate.page_number):
                    break
                if not _should_merge_equation_fragment(equation.text, candidate.text, candidate.kind):
                    break

                equation = DoclingNormalizedItem(
                    kind="equation",
                    text=_merge_equation_text(equation.text, candidate.text),
                    page_number=equation.page_number,
                    heading_level=equation.heading_level,
                    metadata={
                        **equation.metadata,
                        "merged_equation_fragments": equation.metadata.get("merged_equation_fragments", 0) + 1,
                    },
                )
                fragments_merged += 1
                next_index += 1

            if _is_orphan_equation_fragment(equation.text):
                attached = False
                if _looks_like_closing_equation_tail(equation.text):
                    attached = self._attach_orphan_equation_fragment(
                        reconciled=reconciled,
                        orphan=equation,
                        orphan_context=contexts[index],
                    )
                if attached:
                    merged_count += 1
                    index = next_index
                    continue
                orphan_count += 1
                equation = DoclingNormalizedItem(
                    kind="equation",
                    text=equation.text,
                    page_number=equation.page_number,
                    heading_level=equation.heading_level,
                    metadata={**equation.metadata, "equation_fragment_orphan": True},
                )

            merged_count += fragments_merged
            reconciled.append(equation)
            index = next_index

        return reconciled, merged_count, orphan_count

    def _attach_orphan_equation_fragment(
        self,
        *,
        reconciled: list[DoclingNormalizedItem],
        orphan: DoclingNormalizedItem,
        orphan_context: tuple[str, ...],
    ) -> bool:
        for offset, previous in enumerate(reversed(reconciled), start=1):
            if offset > 6:
                break
            if previous.kind in {"heading", "table_caption", "table_row", "figure_caption", "algorithm"}:
                break
            if previous.kind == "paragraph":
                if _looks_like_equation_fragment(previous.text):
                    continue
                break
            if previous.kind != "equation":
                break
            previous_context = tuple(previous.metadata.get("section_context") or ())
            if previous_context and not _same_top_level_context(previous_context, orphan_context):
                return False
            if not _same_or_continuation_page(previous.page_number, orphan.page_number):
                return False
            if not _can_absorb_orphan_equation_fragment(previous.text, orphan.text):
                return False
            merged_metadata = {
                **previous.metadata,
                "merged_equation_fragments": previous.metadata.get("merged_equation_fragments", 0) + 1,
            }
            reconciled[-offset] = DoclingNormalizedItem(
                kind="equation",
                text=_merge_equation_text(previous.text, orphan.text),
                page_number=previous.page_number,
                heading_level=previous.heading_level,
                metadata=merged_metadata,
            )
            return True
        return False

    def _section_contexts(self, items: list[DoclingNormalizedItem]) -> list[tuple[str, ...]]:
        contexts: list[tuple[str, ...]] = []
        heading_stack: list[tuple[int, str]] = []
        for item in items:
            if item.kind == "heading":
                level = item.heading_level or 1
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, item.text))
                context = tuple(text for _, text in heading_stack)
                contexts.append(context)
                item.metadata.setdefault("section_context", context)
            else:
                context = tuple(text for _, text in heading_stack)
                contexts.append(context)
                item.metadata.setdefault("section_context", context)
        return contexts

    def _find_best_caption_for_row(
        self,
        *,
        row_index: int,
        row: DoclingNormalizedItem,
        captions: list[_TableCaptionGroup],
        row_context: tuple[str, ...],
    ) -> _TableCaptionGroup | None:
        normalized_label = _normalize_caption_label(row.metadata.get("caption_label"))
        if normalized_label and normalized_label != "table":
            matching = [caption for caption in captions if caption.caption_label == normalized_label]
            chosen = self._choose_caption_by_proximity(row_index, row, matching, row_context=row_context)
            if chosen is not None:
                return chosen

        same_page = [caption for caption in captions if caption.page_number == row.page_number]
        chosen = self._choose_caption_by_proximity(row_index, row, same_page, row_context=row_context)
        if chosen is not None:
            return chosen

        return self._choose_caption_by_proximity(row_index, row, captions, row_context=row_context)

    def _choose_caption_by_proximity(
        self,
        row_index: int,
        row: DoclingNormalizedItem,
        captions: list[_TableCaptionGroup],
        *,
        row_context: tuple[str, ...],
    ) -> _TableCaptionGroup | None:
        if not captions:
            return None

        def _context_rank(caption: _TableCaptionGroup) -> int:
            if caption.section_context == row_context:
                return 0
            if caption.section_context and row_context and caption.section_context[-1] == row_context[-1]:
                return 1
            return 2

        before = sorted(
            [caption for caption in captions if caption.index < row_index],
            key=lambda caption: (_context_rank(caption), row_index - caption.index),
        )
        if before:
            return before[0]

        after = sorted(
            [caption for caption in captions if caption.index > row_index],
            key=lambda caption: (_context_rank(caption), caption.index - row_index),
        )
        if after:
            return after[0]

        return None

    def _iter_document_items(self, document: Any) -> Iterable[tuple[Any, int | None]]:
        iterator = getattr(document, "iterate_items", None)
        if callable(iterator):
            for entry in iterator():
                yield self._unwrap_iteration_entry(entry)
            return

        texts = getattr(document, "texts", None)
        if texts:
            for entry in texts:
                yield entry, None
            return

        body = getattr(document, "body", None)
        if isinstance(body, list):
            for entry in body:
                yield entry, None

    def _unwrap_iteration_entry(self, entry: Any) -> tuple[Any, int | None]:
        if not isinstance(entry, tuple):
            return entry, None
        if len(entry) == 2:
            item, maybe_level = entry
            return item, maybe_level if isinstance(maybe_level, int) else None
        if entry:
            return entry[0], None
        return entry, None

    def _convert_item(
        self,
        item: Any,
        nesting_level: int | None,
        *,
        state: _ParseState,
        document_title: str | None,
    ) -> _ConvertedItems:
        label = self._item_label(item)
        text = _normalize_whitespace(self._item_text(item))
        page_number = self._page_number(item)

        if not text and label not in {"table", "figure"}:
            return _ConvertedItems()
        if label in _SKIP_LABELS:
            return _ConvertedItems()
        if label in _TITLE_LABELS:
            return _ConvertedItems(title=text or None)
        if document_title and text == document_title:
            return _ConvertedItems()

        if state.in_references:
            if text.strip().upper() == "REFERENCES":
                return self._heading_item(
                    text="REFERENCES",
                    page_number=page_number,
                    heading_level=1,
                    label=label,
                    confidence="high",
                )
            return self._paragraph_item(
                text=text,
                page_number=page_number,
                content_kind="reference",
                label=label,
                confidence="high",
            )

        if abstract_body := _split_abstract_lead(text):
            state.phase = "abstract"
            state.abstract_heading_emitted = True
            items = [
                DoclingNormalizedItem(
                    kind="heading",
                    text="Abstract",
                    page_number=page_number,
                    heading_level=1,
                    metadata={
                        "content_kind": "heading",
                        "docling_label": label or "abstract",
                        "detection_confidence": "high",
                    },
                )
            ]
            if abstract_body:
                items.append(
                    DoclingNormalizedItem(
                        kind="paragraph",
                        text=abstract_body,
                        page_number=page_number,
                        metadata={
                            "content_kind": "paragraph",
                            "docling_label": label,
                            "detection_confidence": "high",
                        },
                    )
                )
            return _ConvertedItems(items=items)

        if label == "table" or _match_table_caption(text):
            return self._convert_table(item, text, page_number)
        if label in _FORMULA_LABELS or (_match_equation_label(text) and _looks_like_equation_text(text)):
            return self._convert_equation(item, text, page_number)
        if label in _FIGURE_LABELS or _match_figure_caption(text):
            return self._convert_figure(item, text, page_number)
        if label in _ALGORITHM_LABELS or _match_algorithm_label(text):
            return self._convert_algorithm(item, text, page_number)
        if text.lower() == "abstract":
            state.phase = "abstract"
            state.abstract_heading_emitted = True
            return self._heading_item(
                text="Abstract",
                page_number=page_number,
                heading_level=1,
                label=label or "abstract",
                confidence="high",
            )

        heading_level = _heading_level_for_item(
            text=text,
            label=label,
            nesting_level=nesting_level,
            saw_body_heading=state.saw_body_heading,
        )
        if heading_level is not None:
            if text.strip().upper() == "REFERENCES":
                state.in_references = True
            extra_metadata = {}
            if _DECIMAL_SUBSECTION_RE.match(text):
                extra_metadata["normalization_promoted_decimal_subsection"] = True
            return self._heading_item(
                text=text,
                page_number=page_number,
                heading_level=heading_level,
                label=label,
                confidence="high" if label in _HEADING_LABELS else "medium",
                extra_metadata=extra_metadata,
            )

        if state.phase == "front_matter" and (label in _FRONT_MATTER_LABELS or _looks_like_front_matter_text(text)):
            return self._front_matter_item(text=text, page_number=page_number, label=label)

        if state.phase == "abstract":
            if _looks_like_index_terms(text):
                return self._front_matter_item(text=text, page_number=page_number, label="index_terms")
            return self._paragraph_item(
                text=text,
                page_number=page_number,
                content_kind="paragraph",
                label=label,
                confidence="high",
            )
        if text:
            if state.phase == "front_matter":
                return self._front_matter_item(text=text, page_number=page_number, label=label)
            return self._paragraph_item(
                text=text,
                page_number=page_number,
                content_kind="paragraph",
                label=label,
                confidence="high",
            )
        return _ConvertedItems()

    def _convert_table(self, item: Any, text: str, page_number: int | None) -> _ConvertedItems:
        warnings: list[str] = []
        table_id = str(uuid4())
        caption_text = _normalize_whitespace(self._table_caption_text(item) or text)
        caption_label = _match_table_caption(caption_text) or _match_table_caption(text) or "Table"
        headers, rows, table_shape = self._table_rows(item)
        table_parse_status = "row_backed" if rows else "caption_only"
        items: list[DoclingNormalizedItem] = []

        if caption_text:
            items.append(
                DoclingNormalizedItem(
                    kind="table_caption",
                    text=caption_text,
                    page_number=page_number,
                    metadata={
                        "content_kind": "table_caption",
                        "caption_label": caption_label,
                        "table_id": table_id,
                        "table_parse_status": table_parse_status,
                        "docling_table_shape": table_shape,
                        "detection_confidence": "high",
                    },
                )
            )

        for row_index, row in enumerate(rows):
            row_text = _format_table_row(headers, row)
            if not row_text:
                continue
            items.append(
                DoclingNormalizedItem(
                    kind="table_row",
                    text=row_text,
                    page_number=page_number,
                    metadata={
                        "content_kind": "table_row",
                        "caption_label": caption_label,
                        "table_id": table_id,
                        "row_index": row_index,
                        "table_headers": headers,
                        "table_parse_status": table_parse_status,
                        "docling_table_shape": table_shape,
                        "detection_confidence": "high",
                    },
                )
            )

        if caption_text and not rows:
            warnings.append(f"Table caption '{caption_label}' had no recoverable table rows.")
        elif not caption_text and not rows and headers:
            items.append(
                DoclingNormalizedItem(
                    kind="table_row",
                    text=" | ".join(_normalize_whitespace(value) for value in headers if _normalize_whitespace(value)),
                    page_number=page_number,
                    metadata={
                        "content_kind": "table_row",
                        "caption_label": caption_label,
                        "table_id": table_id,
                        "row_index": 0,
                        "table_headers": [],
                        "table_parse_status": "row_backed",
                        "docling_table_shape": table_shape,
                        "detection_confidence": "medium",
                    },
                )
            )
        return _ConvertedItems(items=items, warnings=warnings)

    def _convert_equation(self, item: Any, text: str, page_number: int | None) -> _ConvertedItems:
        equation_id = str(uuid4())
        equation_label = self._equation_label(item, text)
        items = [
            DoclingNormalizedItem(
                kind="equation",
                text=text,
                page_number=page_number,
                metadata={
                    "content_kind": "equation",
                    "equation_label": equation_label,
                    "equation_id": equation_id,
                    "docling_label": self._item_label(item),
                    "detection_confidence": "high",
                },
            )
        ]
        explanation = _normalize_whitespace(self._equation_explanation_text(item))
        if explanation:
            items.append(
                DoclingNormalizedItem(
                    kind="equation_explanation",
                    text=explanation,
                    page_number=page_number,
                    metadata={
                        "content_kind": "equation_explanation",
                        "equation_id": equation_id,
                        "detection_confidence": "high",
                    },
                )
            )
        return _ConvertedItems(items=items)

    def _convert_figure(self, item: Any, text: str, page_number: int | None) -> _ConvertedItems:
        caption_text = _normalize_whitespace(self._figure_caption_text(item) or text)
        if not caption_text:
            return _ConvertedItems()
        return _ConvertedItems(
            items=[
                DoclingNormalizedItem(
                    kind="figure_caption",
                    text=caption_text,
                    page_number=page_number,
                    metadata={
                        "content_kind": "figure_caption",
                        "caption_label": _match_figure_caption(caption_text) or "Figure",
                        "related_caption_id": str(uuid4()),
                        "detection_confidence": "high",
                    },
                )
            ]
        )

    def _convert_algorithm(self, item: Any, text: str, page_number: int | None) -> _ConvertedItems:
        algorithm_id = str(uuid4())
        algorithm_label = _match_algorithm_label(text) or self._algorithm_label(item)
        return _ConvertedItems(
            items=[
                DoclingNormalizedItem(
                    kind="algorithm",
                    text=text,
                    page_number=page_number,
                    metadata={
                        "content_kind": "algorithm",
                        "algorithm_label": algorithm_label,
                        "algorithm_id": algorithm_id,
                        "docling_label": self._item_label(item),
                        "detection_confidence": "high",
                    },
                )
            ]
        )

    def _front_matter_item(self, *, text: str, page_number: int | None, label: str) -> _ConvertedItems:
        return self._paragraph_item(
            text=text,
            page_number=page_number,
            content_kind="front_matter",
            label=label,
            confidence="high",
            extra_metadata={
                "exclude_from_chunking": True,
                "exclude_from_retrieval": True,
            },
        )

    def _heading_item(
        self,
        *,
        text: str,
        page_number: int | None,
        heading_level: int,
        label: str,
        confidence: str,
        extra_metadata: dict[str, Any] | None = None,
    ) -> _ConvertedItems:
        metadata = {
            "content_kind": "heading",
            "docling_label": label,
            "detection_confidence": confidence,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        return _ConvertedItems(
            items=[
                DoclingNormalizedItem(
                    kind="heading",
                    text=text,
                    page_number=page_number,
                    heading_level=heading_level,
                    metadata=metadata,
                )
            ]
        )

    def _paragraph_item(
        self,
        *,
        text: str,
        page_number: int | None,
        content_kind: str,
        label: str,
        confidence: str,
        extra_metadata: dict[str, Any] | None = None,
    ) -> _ConvertedItems:
        metadata = {
            "content_kind": content_kind,
            "docling_label": label,
            "detection_confidence": confidence,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        return _ConvertedItems(
            items=[
                DoclingNormalizedItem(
                    kind="paragraph",
                    text=text,
                    page_number=page_number,
                    metadata=metadata,
                )
            ]
        )

    def _extract_document_title(self, document: Any) -> str | None:
        for attribute in ("title", "name"):
            value = getattr(document, attribute, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _extract_page_count(self, document: Any) -> int:
        pages = getattr(document, "pages", None)
        if hasattr(pages, "__len__"):
            return len(pages)
        return 0

    def _item_label(self, item: Any) -> str:
        raw_label = getattr(item, "label", None) or getattr(item, "name", None)
        if hasattr(raw_label, "value"):
            raw_label = raw_label.value
        if raw_label is None:
            raw_label = item.__class__.__name__
        return str(raw_label).strip().lower().replace(" ", "_")

    def _item_text(self, item: Any) -> str:
        for attribute in ("text", "orig", "content", "value"):
            value = getattr(item, attribute, None)
            if isinstance(value, str) and value.strip():
                return value
        caption = self._caption_text(getattr(item, "caption", None))
        return caption or ""

    def _page_number(self, item: Any) -> int | None:
        prov = getattr(item, "prov", None) or getattr(item, "provenance", None) or []
        if isinstance(prov, dict):
            prov = [prov]
        for source in prov:
            if isinstance(source, dict):
                page_number = source.get("page_no") or source.get("page_number")
            else:
                page_number = getattr(source, "page_no", None) or getattr(source, "page_number", None)
            if page_number is not None:
                return int(page_number)
        return getattr(item, "page_no", None)

    def _table_caption_text(self, item: Any) -> str | None:
        return self._caption_text(getattr(item, "caption", None))

    def _figure_caption_text(self, item: Any) -> str | None:
        return self._caption_text(getattr(item, "caption", None))

    def _caption_text(self, caption: Any) -> str | None:
        if caption is None:
            return None
        if isinstance(caption, str):
            return caption
        text = getattr(caption, "text", None) or getattr(caption, "content", None)
        if isinstance(text, str) and text.strip():
            return text
        if isinstance(caption, list):
            parts = [self._caption_text(part) for part in caption]
            return " ".join(part for part in parts if part)
        return None

    def _table_rows(self, item: Any) -> tuple[list[str], list[list[str]], str | None]:
        if hasattr(item, "export_to_dataframe"):
            try:
                dataframe = item.export_to_dataframe()
            except Exception:
                dataframe = None
            if dataframe is not None:
                headers = [str(column).strip() for column in getattr(dataframe, "columns", [])]
                rows = [list(map(_stringify_cell, row)) for row in dataframe.itertuples(index=False, name=None)]
                if rows:
                    return headers, rows, "dataframe"

        for attribute in ("table_data", "data", "rows", "grid", "cells"):
            table_data = getattr(item, attribute, None)
            headers, rows = _coerce_table_rows(table_data)
            if rows or headers:
                return headers, rows, attribute

        return [], [], None

    def _equation_label(self, item: Any, text: str) -> str | None:
        for attribute in ("equation_label", "label_text", "equation_id"):
            value = getattr(item, attribute, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return _match_equation_label(text)

    def _equation_explanation_text(self, item: Any) -> str | None:
        for attribute in ("explanation", "description", "note"):
            value = getattr(item, attribute, None)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _algorithm_label(self, item: Any) -> str | None:
        for attribute in ("algorithm_label", "name"):
            value = getattr(item, attribute, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None


class PdfParser(BaseParser):
    source_type = "pdf"

    def __init__(self, adapter: _DoclingAdapter | None = None) -> None:
        self._adapter = adapter or _DoclingAdapter()

    def parse(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        document_metadata = dict(metadata)
        parsed = self._adapter.convert_pdf(raw_bytes)
        blocks = []
        heading_stack: list[tuple[int, object, str]] = []
        order_index = 0

        def current_parent_id():
            return heading_stack[-1][1] if heading_stack else None

        def current_section_path() -> list[str]:
            return [item[2] for item in heading_stack]

        for item in parsed.items:
            if item.kind == "heading":
                if parsed.title and _normalize_whitespace(item.text) == _normalize_whitespace(parsed.title):
                    continue
                heading_level = item.heading_level or 1
                while heading_stack and heading_stack[-1][0] >= heading_level:
                    heading_stack.pop()
                section_path = [*current_section_path(), item.text]
                block = self.make_block(
                    block_type="heading",
                    text=item.text,
                    order_index=order_index,
                    section_path=section_path,
                    heading_level=heading_level,
                    page_number=item.page_number,
                    parent_block_id=current_parent_id(),
                    metadata=item.metadata,
                )
                blocks.append(block)
                heading_stack.append((heading_level, block.id, item.text))
                order_index += 1
                continue

            block_type = item.kind if item.kind != "paragraph" else "paragraph"
            metadata = item.metadata or {}
            content_kind = metadata.get("content_kind")
            if content_kind == "front_matter":
                section_path = []
                parent_block_id = None
            else:
                section_path = current_section_path()
                parent_block_id = current_parent_id()
            block = self.make_block(
                block_type=block_type,
                text=item.text,
                order_index=order_index,
                section_path=section_path,
                page_number=item.page_number,
                parent_block_id=parent_block_id,
                metadata=metadata,
            )
            blocks.append(block)
            order_index += 1

        title = parsed.title or next((block.text for block in blocks if block.block_type == "heading"), None)
        return self.build_document(
            title=title,
            metadata={
                **document_metadata,
                "page_count": parsed.page_count,
                "parser_backend": "docling",
                "parser_diagnostics": parsed.stats,
            },
            blocks=blocks,
            warnings=parsed.warnings,
        )


_NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\.\s+(.+?)\s*$")
_DECIMAL_SUBSECTION_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)\s+(.+?)\s*$")
_ROMAN_HEADING_RE = re.compile(r"^\s*(?:[IVXLCM]+)\.\s+[A-Z][A-Z0-9\s:,\-()]+$")
_LETTER_HEADING_RE = re.compile(r"^\s*[A-Z]\.\s+[A-Z].+$")
_TABLE_CAPTION_RE = re.compile(r"^\s*(table\s+[ivxlcdm\d]+)\b", re.IGNORECASE)
_FIGURE_CAPTION_RE = re.compile(r"^\s*((?:fig(?:ure)?\.?)\s*\d+[a-z]?)\b", re.IGNORECASE)
_ALGORITHM_RE = re.compile(r"^\s*(algorithm\s+\d+[a-z]?)\b", re.IGNORECASE)
_EQUATION_LABEL_RE = re.compile(r".+\((\d{1,3})\)\s*$")
_ABSTRACT_LEAD_RE = re.compile(r"^\s*abstract\s*[-:—]\s*(.+)$", re.IGNORECASE)

_TITLE_LABELS = {"title", "document_title"}
_FRONT_MATTER_LABELS = {"author", "authors", "affiliation", "email", "keywords", "keyword", "subtitle"}
_SKIP_LABELS = {"page_header", "page_footer"}
_HEADING_LABELS = {
    "heading",
    "header",
    "section_header",
    "section",
    "subsection",
    "chapter",
    "abstract",
}
_FORMULA_LABELS = {"formula", "equation"}
_FIGURE_LABELS = {"figure", "picture", "image"}
_ALGORITHM_LABELS = {"algorithm", "code", "procedure"}


def _normalize_whitespace(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split()).strip()


def _stringify_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _normalize_whitespace(value)
    text = getattr(value, "text", None) or getattr(value, "content", None)
    if isinstance(text, str):
        return _normalize_whitespace(text)
    return _normalize_whitespace(str(value))


def _coerce_table_rows(table_data: Any) -> tuple[list[str], list[list[str]]]:
    if not table_data:
        return [], []
    if isinstance(table_data, dict):
        headers = [_stringify_cell(header) for header in table_data.get("headers", [])]
        rows = [[_stringify_cell(cell) for cell in row] for row in table_data.get("rows", [])]
        return headers, rows
    if not isinstance(table_data, list):
        return [], []

    if table_data and isinstance(table_data[0], dict):
        headers = [str(key).strip() for key in table_data[0].keys()]
        rows = [[_stringify_cell(row.get(header)) for header in headers] for row in table_data]
        return headers, rows

    rows = []
    for row in table_data:
        if isinstance(row, list):
            rows.append([_stringify_cell(cell) for cell in row])
            continue
        if isinstance(row, tuple):
            rows.append([_stringify_cell(cell) for cell in row])
            continue
        cells = getattr(row, "cells", None)
        if cells:
            rows.append([_stringify_cell(cell) for cell in cells])
            continue
        text = _stringify_cell(row)
        if text:
            rows.append([text])
    if not rows:
        return [], []

    headers = rows[0]
    body_rows = rows[1:] if len(rows) > 1 else []
    return headers, body_rows


def _format_table_row(headers: list[str], row: list[str]) -> str:
    cleaned_row = [_normalize_whitespace(cell) for cell in row if _normalize_whitespace(cell)]
    if not cleaned_row:
        return ""
    if headers and len(headers) == len(row):
        return _format_table_pairs(headers, row)
    if headers and len(headers) > 1 and len(row) == len(headers) - 1:
        pairs = [f"{header}: {value}" for header, value in zip(headers[1:], row) if _normalize_whitespace(value)]
        if row[0]:
            pairs.insert(0, f"{headers[0]}: {row[0]}")
        return " | ".join(pairs)
    return " | ".join(cleaned_row)


def _format_table_pairs(headers: list[str], row: list[str]) -> str:
    pairs = [f"{header}: {value}" for header, value in zip(headers, row) if _normalize_whitespace(value)]
    return " | ".join(pairs)


def _usable_table_headers(headers: list[str]) -> list[str]:
    cleaned = [_normalize_whitespace(header) for header in headers if _normalize_whitespace(header)]
    if not cleaned:
        return []
    if all(re.fullmatch(r"\d+", header) for header in cleaned):
        return []
    return cleaned


def _as_front_matter_item(item: DoclingNormalizedItem) -> DoclingNormalizedItem:
    metadata = {
        **item.metadata,
        "content_kind": "front_matter",
        "exclude_from_chunking": True,
        "exclude_from_retrieval": True,
    }
    return DoclingNormalizedItem(
        kind="paragraph",
        text=item.text,
        page_number=item.page_number,
        metadata=metadata,
    )


def _looks_like_heading(text: str) -> bool:
    if not text or len(text) > 140:
        return False
    if _match_table_caption(text) or _match_figure_caption(text) or _match_algorithm_label(text):
        return False
    return bool(
        _NUMBERED_HEADING_RE.match(text)
        or _DECIMAL_SUBSECTION_RE.match(text)
        or _ROMAN_HEADING_RE.match(text)
        or _LETTER_HEADING_RE.match(text)
    )


def _heading_level_for_item(
    *,
    text: str,
    label: str,
    nesting_level: int | None,
    saw_body_heading: bool,
) -> int | None:
    if text.strip().upper() == "REFERENCES":
        return 1
    if _is_structural_section_heading(text):
        return _infer_heading_level(text, nesting_level)
    if saw_body_heading and _DECIMAL_SUBSECTION_RE.match(text) and _should_promote_decimal_heading(text):
        return _infer_heading_level(text, nesting_level)
    if saw_body_heading and _LETTER_HEADING_RE.match(text):
        return _infer_heading_level(text, nesting_level)
    if label in _HEADING_LABELS and _NUMBERED_HEADING_RE.match(text):
        return _infer_heading_level(text, nesting_level)
    return None


def _infer_heading_level(text: str, nesting_level: int | None) -> int:
    if text.lower() == "abstract":
        return 1
    if _is_structural_section_heading(text):
        return 1
    decimal_match = _DECIMAL_SUBSECTION_RE.match(text)
    if decimal_match:
        inferred = _decimal_heading_level(decimal_match.group(1))
        return max(inferred, nesting_level or inferred)
    if _LETTER_HEADING_RE.match(text):
        return max(2, nesting_level or 2)
    numbered_match = _NUMBERED_HEADING_RE.match(text)
    if numbered_match:
        inferred = numbered_match.group(1).count(".") + 1
        return max(inferred, nesting_level or inferred)
    if nesting_level is not None:
        return max(1, nesting_level)
    return 1


def _match_table_caption(text: str) -> str | None:
    match = _TABLE_CAPTION_RE.match(text)
    return match.group(1).strip() if match else None


def _match_figure_caption(text: str) -> str | None:
    match = _FIGURE_CAPTION_RE.match(text)
    return match.group(1).strip() if match else None


def _match_algorithm_label(text: str) -> str | None:
    match = _ALGORITHM_RE.match(text)
    return match.group(1).strip() if match else None


def _match_equation_label(text: str) -> str | None:
    match = _EQUATION_LABEL_RE.match(text)
    return match.group(1) if match else None


def _looks_like_equation_text(text: str) -> bool:
    normalized = _normalize_whitespace(text)
    if not normalized or len(normalized) > 220:
        return False
    if normalized.lower().startswith(("where ", "thus ", "therefore ")):
        return False
    operators = sum(normalized.count(symbol) for symbol in ("=", "+", "-", "*", "/", "^", "≤", "≥", "<", ">"))
    variable_markers = sum(1 for char in normalized if char.isalpha())
    has_equation_label = _match_equation_label(normalized) is not None
    return operators >= 1 and variable_markers >= 2 and (has_equation_label or operators >= 2 or len(normalized) <= 80)


def _looks_like_equation_explanation(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in ("where ", "denotes", "represents", "is the", "are the", "measures", "computes")
    )


def _looks_like_algorithm_step(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.match(r"^\s*(?:step\s*\d+|input:|output:|require:|ensure:|\d+\)|\d+\.)", lowered)
        or lowered.startswith(("if ", "for ", "while ", "return "))
    )


def _is_structural_section_heading(text: str) -> bool:
    stripped = text.strip()
    return bool(_NUMBERED_HEADING_RE.match(stripped) or _ROMAN_HEADING_RE.match(stripped))


def _split_abstract_lead(text: str) -> str | None:
    match = _ABSTRACT_LEAD_RE.match(text)
    if not match:
        return None
    return _normalize_whitespace(match.group(1))


def _looks_like_index_terms(text: str) -> bool:
    lowered = text.lower()
    return lowered.startswith("index terms") or lowered.startswith("keywords")


def _looks_like_front_matter_text(text: str) -> bool:
    lowered = text.lower()
    if _looks_like_index_terms(text):
        return True
    if any(marker in lowered for marker in ("roll no", "department of", "university", "bsai", "bsds", "@")):
        return True
    if len(text.split()) <= 6 and all(part[:1].isupper() for part in text.split() if part and part[0].isalpha()):
        return True
    return False


def _is_front_matter_continuation(previous_text: str, current_text: str) -> bool:
    previous = _normalize_whitespace(previous_text)
    current = _normalize_whitespace(current_text)
    if not previous or not current:
        return False
    if previous.endswith("-"):
        return True
    if _looks_like_index_terms(previous_text) and current[:1].islower():
        return True
    if previous.lower().startswith(("index terms", "keywords")) and len(current.split()) <= 20:
        return True
    return False


def _normalize_caption_label(value: Any) -> str | None:
    if value is None:
        return None
    normalized = _normalize_whitespace(str(value))
    return normalized.lower() if normalized else None


def _tokenize_title_tokens(title: str | None) -> set[str]:
    if not title:
        return set()
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9]+", title)
        if len(token) > 2
    }


def _looks_like_page_artifact_line(text: str, *, title_tokens: set[str]) -> bool:
    normalized = _normalize_whitespace(text)
    if not normalized or len(normalized) > 120:
        return False
    if _looks_like_heading(normalized) or _looks_like_equation_text(normalized):
        return False
    tokens = {token.lower() for token in re.findall(r"[A-Za-z0-9]+", normalized) if len(token) > 2}
    title_overlap = len(tokens & title_tokens) >= 2 if title_tokens else False
    words = [word for word in normalized.replace("·", " ").split() if word]
    uppercase_starts = sum(1 for word in words if not word[0].isalpha() or word[0].isupper())
    title_like = bool(words) and uppercase_starts >= max(2, len(words) - 2)
    has_banner_marker = any(marker in normalized.lower() for marker in ("version", "research division", "may 20", "june 20"))
    return (title_like and len(normalized.split()) <= 10 and (title_overlap or len(normalized.split()) <= 7)) or has_banner_marker


def _is_suppressible_artifact_run(run: list[DoclingNormalizedItem], *, title_tokens: set[str]) -> bool:
    if len(run) < 2:
        return False
    return any(
        any(marker in item.text.lower() for marker in ("version", "research division"))
        or len({token.lower() for token in re.findall(r"[A-Za-z0-9]+", item.text)} & title_tokens) >= 2
        for item in run
    )


def _should_promote_decimal_heading(text: str) -> bool:
    normalized = _normalize_whitespace(text)
    match = _DECIMAL_SUBSECTION_RE.match(normalized)
    if not match or len(normalized) > 140:
        return False
    if normalized.endswith((".", "?", "!")):
        return False
    if any(token in normalized for token in ("=", "|", "Table ", "Figure ", "Fig.")):
        return False
    words = match.group(2).split()
    if len(words) > 14:
        return False
    return all(not word or not word[0].islower() for word in words[:4])


def _decimal_heading_level(prefix: str) -> int:
    return prefix.count(".") + 1


def _row_uses_positional_fields(text: str) -> bool:
    return bool(re.search(r"(?:^|\|\s*)\d+:\s*", text))


def _parse_positional_row_values(text: str) -> list[str]:
    parts = [part.strip() for part in text.split("|")]
    values: list[str] = []
    for part in parts:
        if ":" not in part:
            continue
        _, value = part.split(":", 1)
        values.append(_normalize_whitespace(value))
    return values


def _same_section_context(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return left == right


def _same_top_level_context(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    if not left or not right:
        return True
    return left[0] == right[0]


def _same_or_continuation_page(left: int | None, right: int | None) -> bool:
    if left is None or right is None:
        return True
    return right in {left, left + 1}


def _should_merge_equation_fragment(current_text: str, candidate_text: str, candidate_kind: str) -> bool:
    current = _normalize_whitespace(current_text)
    candidate = _normalize_whitespace(candidate_text)
    if not candidate:
        return False
    if candidate_kind == "paragraph":
        return _equation_appears_incomplete(current) and _looks_like_equation_fragment(candidate)
    return _equation_appears_incomplete(current) and _looks_like_equation_fragment(candidate)


def _equation_appears_incomplete(text: str) -> bool:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return False
    if normalized.endswith(("=", "+", "-", "*", "/", "(", "[", "{")):
        return True
    if normalized.count("(") > normalized.count(")") or normalized.count("[") > normalized.count("]"):
        return True
    if re.search(r"(?:\b\w+\s*)\^\s*$", normalized):
        return True
    if re.search(r"/\s*$", normalized):
        return True
    if re.search(r"\b(?:sin|cos|tan|log|exp|max|min)\s*\([^)]*$", normalized, re.IGNORECASE):
        return True
    return False


def _looks_like_equation_fragment(text: str) -> bool:
    normalized = _normalize_whitespace(text)
    if not normalized or len(normalized) > 120:
        return False
    if _looks_like_equation_explanation(normalized):
        return False
    symbol_count = sum(1 for char in normalized if char in "=+-*/^()[]{}<>")
    alpha_count = sum(1 for char in normalized if char.isalpha())
    if len(normalized) <= 12 and symbol_count >= 1:
        return True
    if _looks_like_closing_equation_tail(normalized):
        return True
    return symbol_count >= 2 and alpha_count <= max(6, len(normalized) // 3)


def _is_orphan_equation_fragment(text: str) -> bool:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return False
    return len(normalized) <= 12 and _looks_like_equation_fragment(normalized)


def _merge_equation_text(left: str, right: str) -> str:
    merged = f"{_normalize_whitespace(left)} {_normalize_whitespace(right)}"
    merged = re.sub(r"\s+([)\]\}])", r"\1", merged)
    merged = re.sub(r"([(\[\{])\s+", r"\1", merged)
    return _normalize_whitespace(merged)


def _looks_like_closing_equation_tail(text: str) -> bool:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return False
    return bool(
        re.match(r"^[)\]}\s]+(?:\d+|[a-z]\b|[+\-*/^=].*)?$", normalized, re.IGNORECASE)
        or re.match(r"^\^\s*\d+$", normalized)
    )


def _can_absorb_orphan_equation_fragment(previous_text: str, orphan_text: str) -> bool:
    if not _looks_like_closing_equation_tail(orphan_text):
        return False
    return _equation_appears_incomplete(previous_text)


def _count_promoted_decimal_subsections(items: list[DoclingNormalizedItem]) -> int:
    return sum(
        1
        for item in items
        if item.kind == "heading" and item.metadata.get("normalization_promoted_decimal_subsection") is True
    )
