from __future__ import annotations

from io import BytesIO
import re
from uuid import uuid4

from pypdf import PdfReader

from app.domain.entities.rag import ExtractedDocument
from app.ingestion.parsers.base import BaseParser


class PdfParser(BaseParser):
    source_type = "pdf"

    def parse(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        reader = PdfReader(BytesIO(raw_bytes))
        blocks = []
        warnings: list[str] = []
        heading_stack: list[tuple[int, object, str]] = []
        current_table_id = None
        current_table_label: str | None = None
        current_table_headers: list[str] = []
        current_equation_id = None
        current_algorithm_id = None
        current_algorithm_label: str | None = None
        saw_named_section = False
        front_matter_mode = True
        order_index = 0

        def current_parent_id():
            return heading_stack[-1][1] if heading_stack else None

        def current_section_path():
            return [item[2] for item in heading_stack]

        def close_active_structures():
            nonlocal current_table_id
            nonlocal current_table_label
            nonlocal current_table_headers
            nonlocal current_equation_id
            nonlocal current_algorithm_id
            nonlocal current_algorithm_label
            current_table_id = None
            current_table_label = None
            current_table_headers = []
            current_equation_id = None
            current_algorithm_id = None
            current_algorithm_label = None

        def apply_heading(heading_text: str, heading_level: int, page_number: int):
            nonlocal order_index
            nonlocal saw_named_section
            nonlocal front_matter_mode
            while heading_stack and heading_stack[-1][0] >= heading_level:
                heading_stack.pop()
            block = self.make_block(
                block_type="heading",
                text=heading_text,
                order_index=order_index,
                section_path=[*current_section_path(), heading_text],
                heading_level=heading_level,
                page_number=page_number,
                parent_block_id=current_parent_id(),
            )
            blocks.append(block)
            heading_stack.append((heading_level, block.id, heading_text))
            if _is_structural_section_heading(heading_text):
                saw_named_section = True
                front_matter_mode = False
            order_index += 1

        def flush_paragraph(lines: list[str], page_number: int):
            nonlocal order_index
            text = ' '.join(part.strip() for part in lines if part.strip()).strip()
            if not text:
                return
            block = self.make_block(
                block_type='paragraph',
                text=text,
                order_index=order_index,
                section_path=current_section_path(),
                page_number=page_number,
                parent_block_id=current_parent_id(),
            )
            blocks.append(block)
            order_index += 1

        def append_structure_block(
            *,
            block_type: str,
            text: str,
            page_number: int,
            metadata: dict | None = None,
            parent_block_id=None,
        ):
            nonlocal order_index
            block = self.make_block(
                block_type=block_type,
                text=text,
                order_index=order_index,
                section_path=current_section_path(),
                page_number=page_number,
                parent_block_id=parent_block_id if parent_block_id is not None else current_parent_id(),
                metadata=metadata or {},
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
                    if current_equation_id is not None:
                        current_equation_id = None
                    continue
                abstract_match = _split_abstract_line(line)
                if abstract_match is not None:
                    flush_paragraph(paragraph_lines, page_number)
                    paragraph_lines = []
                    heading_text, body_text = abstract_match
                    apply_heading(heading_text, 1 if not saw_named_section else 2, page_number)
                    if body_text:
                        paragraph_lines.append(body_text)
                    continue
                if _looks_like_front_matter_noise(line, saw_named_section=saw_named_section, front_matter_mode=front_matter_mode):
                    flush_paragraph(paragraph_lines, page_number)
                    paragraph_lines = []
                    continue
                if caption := _match_table_caption(line):
                    flush_paragraph(paragraph_lines, page_number)
                    paragraph_lines = []
                    current_table_id = uuid4()
                    current_table_label = caption
                    current_table_headers = []
                    current_equation_id = None
                    current_algorithm_id = None
                    current_algorithm_label = None
                    append_structure_block(
                        block_type="table_caption",
                        text=line,
                        page_number=page_number,
                        metadata={
                            "content_kind": "table_caption",
                            "caption_label": caption,
                            "table_id": str(current_table_id),
                            "detection_confidence": "high",
                        },
                    )
                    continue
                if equation_label := _match_equation_label(line):
                    flush_paragraph(paragraph_lines, page_number)
                    paragraph_lines = []
                    current_table_id = None
                    current_table_label = None
                    current_table_headers = []
                    current_equation_id = uuid4()
                    append_structure_block(
                        block_type="equation",
                        text=line,
                        page_number=page_number,
                        metadata={
                            "content_kind": "equation",
                            "equation_label": equation_label,
                            "equation_id": str(current_equation_id),
                            "detection_confidence": "high",
                        },
                    )
                    continue
                if caption := _match_figure_caption(line):
                    flush_paragraph(paragraph_lines, page_number)
                    paragraph_lines = []
                    close_active_structures()
                    append_structure_block(
                        block_type="figure_caption",
                        text=line,
                        page_number=page_number,
                        metadata={
                            "content_kind": "figure_caption",
                            "caption_label": caption,
                            "detection_confidence": "high",
                        },
                    )
                    continue
                if algorithm_label := _match_algorithm_label(line):
                    flush_paragraph(paragraph_lines, page_number)
                    paragraph_lines = []
                    current_algorithm_id = uuid4()
                    current_algorithm_label = algorithm_label
                    current_equation_id = None
                    append_structure_block(
                        block_type="algorithm",
                        text=line,
                        page_number=page_number,
                        metadata={
                            "content_kind": "algorithm",
                            "algorithm_label": algorithm_label,
                            "algorithm_id": str(current_algorithm_id),
                            "detection_confidence": "high",
                        },
                    )
                    continue
                if current_table_id is not None and _looks_like_table_row(line, current_table_headers):
                    current_table_headers = current_table_headers or _extract_table_headers(line)
                    append_structure_block(
                        block_type="table_row",
                        text=line,
                        page_number=page_number,
                        metadata={
                            "content_kind": "table_row",
                            "caption_label": current_table_label,
                            "table_id": str(current_table_id),
                            "row_index": _table_row_index(blocks, current_table_id),
                            "table_headers": current_table_headers,
                            "detection_confidence": "medium" if current_table_headers else "low",
                        },
                    )
                    continue
                if current_table_id is not None and _looks_like_table_continuation(line):
                    append_structure_block(
                        block_type="table_row",
                        text=line,
                        page_number=page_number,
                        metadata={
                            "content_kind": "table_row",
                            "caption_label": current_table_label,
                            "table_id": str(current_table_id),
                            "row_index": _table_row_index(blocks, current_table_id),
                            "table_headers": current_table_headers,
                            "detection_confidence": "low",
                        },
                    )
                    continue
                heading = _extract_heading(line, has_top_level=bool(heading_stack and heading_stack[0][0] == 1))
                if heading is not None:
                    flush_paragraph(paragraph_lines, page_number)
                    paragraph_lines = []
                    close_active_structures()
                    heading_text, body_text, heading_level = heading
                    apply_heading(heading_text, heading_level, page_number)
                    if body_text:
                        paragraph_lines.append(body_text)
                    continue
                if current_equation_id is not None and _looks_like_equation_explanation(line):
                    append_structure_block(
                        block_type="equation_explanation",
                        text=line,
                        page_number=page_number,
                        metadata={
                            "content_kind": "equation_explanation",
                            "equation_id": str(current_equation_id),
                            "detection_confidence": "medium",
                        },
                    )
                    current_equation_id = None
                    continue
                if current_algorithm_id is not None and _looks_like_algorithm_step(line):
                    append_structure_block(
                        block_type="algorithm",
                        text=line,
                        page_number=page_number,
                        metadata={
                            "content_kind": "algorithm",
                            "algorithm_label": current_algorithm_label,
                            "algorithm_id": str(current_algorithm_id),
                            "detection_confidence": "medium",
                        },
                    )
                    continue
                if current_table_id is not None and _looks_like_end_of_table(line):
                    current_table_id = None
                    current_table_label = None
                    current_table_headers = []
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


_NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\.\s+(.+?)\s*$")
_ROMAN_HEADING_RE = re.compile(r"^\s*(?:[IVXLCM]+)\.\s+[A-Z][A-Z0-9\s:,\-()]+$")
_ABSTRACT_RE = re.compile(r"^\s*abstract(?:\s*[-:—]\s*|\s+)(.+)$", re.IGNORECASE)
_TABLE_CAPTION_RE = re.compile(r"^\s*(table\s+[ivxlcdm\d]+)\b", re.IGNORECASE)
_FIGURE_CAPTION_RE = re.compile(r"^\s*((?:fig(?:ure)?\.?)\s*\d+[a-z]?)\b", re.IGNORECASE)
_ALGORITHM_RE = re.compile(r"^\s*(algorithm\s+\d+[a-z]?)\b", re.IGNORECASE)
_EQUATION_LABEL_RE = re.compile(r".+\(\d{1,3}\)\s*$")
_HEADING_CONNECTORS = {"and", "of", "the", "for", "to", "in", "on", "or", "with", "&"}


def _extract_heading(line: str, *, has_top_level: bool) -> tuple[str, str | None, int] | None:
    stripped = line.strip()
    numbered = _split_numbered_heading(stripped)
    if numbered is not None:
        return numbered
    if _ROMAN_HEADING_RE.match(stripped):
        return stripped, None, 1
    if not _looks_like_heading(stripped):
        return None
    level = 2 if stripped.endswith(":") and has_top_level else 1
    return stripped, None, level


def _split_numbered_heading(line: str) -> tuple[str, str | None, int] | None:
    match = _NUMBERED_HEADING_RE.match(line)
    if not match:
        return None
    numbering, remainder = match.groups()
    level = numbering.count(".") + 1
    words = remainder.split()
    heading_words: list[str] = []
    body_start = len(words)

    for index, word in enumerate(words):
        normalized = word.strip(",;:()[]{}")
        next_word = words[index + 1] if index + 1 < len(words) else None
        next_normalized = next_word.strip(",;:()[]{}") if next_word else ""

        if heading_words and _is_title_like(normalized) and _starts_body_phrase(next_normalized):
            body_start = index
            break
        if heading_words and not _is_heading_word(normalized):
            body_start = index
            break
        if not heading_words and not _is_title_like(normalized):
            return None
        heading_words.append(word)

    heading_text = f"{numbering}. {' '.join(heading_words)}".strip()
    body_text = " ".join(words[body_start:]).strip() if body_start < len(words) else None
    if body_text and len(heading_words) < 2:
        return None
    return heading_text, body_text or None, level


def _is_heading_word(value: str) -> bool:
    return _is_title_like(value) or value.lower() in _HEADING_CONNECTORS


def _starts_body_phrase(next_word: str) -> bool:
    if not next_word:
        return False
    if next_word.lower() in _HEADING_CONNECTORS:
        return False
    return next_word[:1].islower()


def _is_title_like(value: str) -> bool:
    if not value:
        return False
    if value.isupper():
        return True
    return value[0].isupper() and value[1:] == value[1:].lower()


def _looks_like_heading(line: str) -> bool:
    if len(line) < 4 or len(line) > 120:
        return False
    if _match_table_caption(line) or _match_figure_caption(line) or _match_algorithm_label(line) or _match_equation_label(line):
        return False
    if line.endswith(('.', ';', '?', '!')):
        return False
    alpha_chars = [char for char in line if char.isalpha()]
    if not alpha_chars:
        return False
    uppercase_ratio = sum(1 for char in alpha_chars if char.isupper()) / len(alpha_chars)
    title_case = line == line.title()
    return uppercase_ratio > 0.8 or title_case


def _split_abstract_line(line: str) -> tuple[str, str] | None:
    match = _ABSTRACT_RE.match(line)
    if not match:
        return None
    return "Abstract", match.group(1).strip()


def _looks_like_front_matter_noise(line: str, *, saw_named_section: bool, front_matter_mode: bool) -> bool:
    if saw_named_section or not front_matter_mode:
        return False
    if _ROMAN_HEADING_RE.match(line.strip()) or _NUMBERED_HEADING_RE.match(line.strip()):
        return False
    lowered = line.lower()
    if lowered.startswith("roll no"):
        return True
    if any(marker in lowered for marker in ("@gmail.com", "@nu.edu.pk", "@", "department of", "faculty of", "university", "campus")):
        return True
    if line in {"Pakistan", "Islamabad", "Rawalpindi"}:
        return True
    words = line.split()
    if 1 < len(words) <= 4 and all(word[:1].isupper() for word in words if word and word[0].isalpha()):
        return True
    return False


def _match_table_caption(line: str) -> str | None:
    match = _TABLE_CAPTION_RE.match(line)
    return match.group(1).strip() if match else None


def _match_figure_caption(line: str) -> str | None:
    match = _FIGURE_CAPTION_RE.match(line)
    return match.group(1).strip() if match else None


def _match_algorithm_label(line: str) -> str | None:
    match = _ALGORITHM_RE.match(line)
    return match.group(1).strip() if match else None


def _match_equation_label(line: str) -> str | None:
    if not _EQUATION_LABEL_RE.match(line):
        return None
    symbol_count = sum(1 for char in line if char in "=+-*/^∑∏λβσμ≤≥")
    return line.rsplit("(", 1)[-1].rstrip(")") if symbol_count > 0 else None


def _looks_like_table_row(line: str, headers: list[str]) -> bool:
    if _match_table_caption(line) or _match_figure_caption(line) or _match_algorithm_label(line):
        return False
    tokens = line.split()
    if len(tokens) < 3:
        return False
    numberish = sum(1 for token in tokens if any(char.isdigit() for char in token))
    compact = len(line) < 180 and ("|" in line or "\t" in line)
    if compact:
        return True
    if headers and numberish >= 1:
        return True
    if numberish >= 1 and len(tokens) >= 3 and tokens[-1][0].isdigit():
        return True
    alpha_ratio = sum(1 for char in line if char.isalpha()) / max(1, len(line))
    return numberish >= 2 and alpha_ratio < 0.75


def _looks_like_table_continuation(line: str) -> bool:
    if len(line) > 220:
        return False
    tokens = line.split()
    if len(tokens) < 2:
        return False
    return sum(1 for token in tokens if any(char.isdigit() for char in token)) >= 2


def _extract_table_headers(line: str) -> list[str]:
    tokens = [token.strip(",:;") for token in line.split()]
    headers = [token for token in tokens if token and token[0].isupper() and not any(char.isdigit() for char in token)]
    return headers[:8]


def _table_row_index(blocks: list, table_id) -> int:
    return sum(1 for block in blocks if block.metadata.get("table_id") == str(table_id) and block.block_type == "table_row")


def _looks_like_equation_explanation(line: str) -> bool:
    lowered = line.lower()
    return any(
        phrase in lowered
        for phrase in ("where ", "denotes", "represents", "is the", "are the", "measures", "computes")
    ) and line.endswith(".")


def _looks_like_algorithm_step(line: str) -> bool:
    lowered = line.lower()
    return bool(
        re.match(r"^\s*(?:step\s*\d+|input:|output:|require:|ensure:|\d+\)|\d+\.)", lowered)
        or lowered.startswith(("if ", "for ", "while ", "return "))
    )


def _looks_like_end_of_table(line: str) -> bool:
    return bool(_ROMAN_HEADING_RE.match(line) or _NUMBERED_HEADING_RE.match(line) or _match_figure_caption(line))


def _is_structural_section_heading(text: str) -> bool:
    stripped = text.strip()
    if stripped.lower() == "abstract":
        return False
    return bool(_ROMAN_HEADING_RE.match(stripped) or _NUMBERED_HEADING_RE.match(stripped))
