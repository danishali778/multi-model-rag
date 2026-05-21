from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.domain.entities.rag import ExtractedBlock, ExtractedDocument


@dataclass(slots=True)
class ChunkDraft:
    chunk_index: int
    content: str
    token_count: int
    metadata: dict[str, Any]
    parent_block_id: Any | None = None
    chunk_role: str = "child"
    page_number: int | None = None
    chunk_type: str | None = None
    section_title: str | None = None
    subsection_title: str | None = None
    section_path: list[str] | None = None
    block_order_start: int | None = None
    block_order_end: int | None = None


def _token_count(text: str) -> int:
    try:
        encoder = tiktoken.get_encoding("cl100k_base")
        return len(encoder.encode(text))
    except Exception:
        return max(1, len(text.split()))


def chunk_text(
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    base_metadata: dict[str, Any] | None = None,
) -> list[ChunkDraft]:
    metadata = dict(base_metadata or {})
    document = ExtractedDocument(
        text=text,
        detected_source_type=str(metadata.get("source_type") or "text"),
        title=metadata.get("title") if isinstance(metadata.get("title"), str) else None,
        metadata=metadata,
        blocks=[
            ExtractedBlock(
                id=metadata.get("_synthetic_block_id") or uuid4(),
                block_type="paragraph",
                text=text,
                page_number=None,
                heading_level=None,
                section_path=[],
                order_index=0,
                parent_block_id=None,
                metadata={},
            )
        ],
        section_tree=[],
        warnings=[],
    )
    return chunk_document(
        document=document,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        base_metadata=metadata,
    )


def chunk_document(
    document: ExtractedDocument,
    *,
    chunk_size: int,
    chunk_overlap: int,
    base_metadata: dict[str, Any] | None = None,
) -> list[ChunkDraft]:
    groups = _build_groups(document.blocks)
    chunks: list[ChunkDraft] = []
    next_index = 0
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    metadata = dict(base_metadata or {})

    for group in groups:
        built_chunks, next_index = _build_group_chunks(
            group=group,
            base_metadata=metadata,
            splitter=splitter,
            chunk_size=chunk_size,
            next_index=next_index,
        )
        chunks.extend(built_chunks)
    return chunks


def _build_groups(blocks: list[ExtractedBlock]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for block in sorted(blocks, key=lambda item: item.order_index):
        if block.block_type == "heading":
            current = None
            continue
        structure_group_id = _structure_group_id(block)
        group_parent_id = block.parent_block_id or tuple(block.section_path) or block.id
        key = (tuple(block.section_path), structure_group_id or group_parent_id)
        chunk_type = _group_chunk_type(block)
        if current is None or current["key"] != key:
            current = {
                "key": key,
                "parent_block_id": group_parent_id if not isinstance(group_parent_id, tuple) else None,
                "section_path": list(block.section_path),
                "section_title": block.section_path[0] if block.section_path else None,
                "subsection_title": block.section_path[-1] if len(block.section_path) > 1 else None,
                "page_number": block.page_number,
                "chunk_type": chunk_type,
                "content_kind": block.metadata.get("content_kind", block.block_type),
                "structure_group_id": structure_group_id,
                "block_order_start": block.order_index,
                "block_order_end": block.order_index,
                "blocks": [block],
            }
            groups.append(current)
        else:
            current["blocks"].append(block)
            current["block_order_end"] = block.order_index
    return groups


def _render_group_text(group: dict[str, Any]) -> str:
    header = " > ".join(group["section_path"]).strip()
    body_parts: list[str] = []
    for block in group["blocks"]:
        if block.block_type == "list_item":
            body_parts.append(f"- {block.text.strip()}")
        else:
            body_parts.append(block.text.strip())
    body = "\n\n".join(part for part in body_parts if part)
    if header and body:
        return f"{header}\n\n{body}".strip()
    return body.strip() or header


def _build_group_chunks(
    *,
    group: dict[str, Any],
    base_metadata: dict[str, Any],
    splitter: RecursiveCharacterTextSplitter,
    chunk_size: int,
    next_index: int,
) -> tuple[list[ChunkDraft], int]:
    content_kind = group.get("content_kind")
    if content_kind in {"table_caption", "table_row"}:
        return _build_table_chunks(group, base_metadata=base_metadata, next_index=next_index)
    if content_kind in {"equation", "equation_explanation"}:
        return _build_equation_chunks(group, base_metadata=base_metadata, next_index=next_index)
    if content_kind == "algorithm":
        return _build_algorithm_chunks(
            group,
            base_metadata=base_metadata,
            splitter=splitter,
            chunk_size=chunk_size,
            next_index=next_index,
        )
    if content_kind == "figure_caption":
        return _build_caption_chunks(group, base_metadata=base_metadata, next_index=next_index)
    return _build_prose_chunks(
        group,
        base_metadata=base_metadata,
        splitter=splitter,
        chunk_size=chunk_size,
        next_index=next_index,
    )


def _build_prose_chunks(
    group: dict[str, Any],
    *,
    base_metadata: dict[str, Any],
    splitter: RecursiveCharacterTextSplitter,
    chunk_size: int,
    next_index: int,
) -> tuple[list[ChunkDraft], int]:
    parent_text = _render_group_text(group)
    if not parent_text.strip():
        return [], next_index
    common_metadata = _common_chunk_metadata(group, base_metadata)
    parent_block_id = group["parent_block_id"]
    parent_chunk = ChunkDraft(
        chunk_index=next_index,
        content=parent_text,
        token_count=_token_count(parent_text),
        metadata=dict(common_metadata),
        parent_block_id=parent_block_id,
        chunk_role="parent",
        page_number=group["page_number"],
        chunk_type=group["chunk_type"],
        section_title=group["section_title"],
        subsection_title=group["subsection_title"],
        section_path=list(group["section_path"]),
        block_order_start=group["block_order_start"],
        block_order_end=group["block_order_end"],
    )
    chunks = [parent_chunk]
    next_index += 1

    child_parts = [parent_text]
    if parent_chunk.token_count > chunk_size:
        child_parts = splitter.split_text(parent_text)

    for part in child_parts:
        child_metadata = dict(common_metadata)
        child_metadata["parent_chunk_index"] = parent_chunk.chunk_index
        chunks.append(
            ChunkDraft(
                chunk_index=next_index,
                content=part,
                token_count=_token_count(part),
                metadata=child_metadata,
                parent_block_id=parent_block_id,
                chunk_role="child",
                page_number=group["page_number"],
                chunk_type=group["chunk_type"],
                section_title=group["section_title"],
                subsection_title=group["subsection_title"],
                section_path=list(group["section_path"]),
                block_order_start=group["block_order_start"],
                block_order_end=group["block_order_end"],
            )
        )
        next_index += 1
    return chunks, next_index


def _build_table_chunks(
    group: dict[str, Any],
    *,
    base_metadata: dict[str, Any],
    next_index: int,
) -> tuple[list[ChunkDraft], int]:
    blocks = group["blocks"]
    caption_block = next((block for block in blocks if block.block_type == "table_caption"), None)
    row_blocks = [block for block in blocks if block.block_type == "table_row"]
    caption_text = caption_block.text.strip() if caption_block else "Table"
    summary_lines = [caption_text]
    if row_blocks:
        summary_lines.extend(block.text.strip() for block in row_blocks[: min(3, len(row_blocks))])
        if len(row_blocks) > 3:
            summary_lines.append(f"... {len(row_blocks) - 3} more table rows")
    parent_text = "\n".join(line for line in summary_lines if line).strip()
    if not parent_text:
        return [], next_index

    common_metadata = _common_chunk_metadata(group, base_metadata)
    common_metadata["content_kind"] = "table"
    common_metadata["caption_label"] = caption_block.metadata.get("caption_label") if caption_block else None
    common_metadata["table_id"] = _structure_group_id(caption_block or row_blocks[0])
    common_metadata["table_headers"] = _merged_table_headers(row_blocks)
    parent_block_id = group["parent_block_id"]
    parent_chunk = ChunkDraft(
        chunk_index=next_index,
        content=parent_text,
        token_count=_token_count(parent_text),
        metadata=dict(common_metadata),
        parent_block_id=parent_block_id,
        chunk_role="parent",
        page_number=group["page_number"],
        chunk_type="table",
        section_title=group["section_title"],
        subsection_title=group["subsection_title"],
        section_path=list(group["section_path"]),
        block_order_start=group["block_order_start"],
        block_order_end=group["block_order_end"],
    )
    chunks = [parent_chunk]
    next_index += 1

    for row_block in row_blocks or ([caption_block] if caption_block else []):
        child_metadata = dict(common_metadata)
        child_metadata["parent_chunk_index"] = parent_chunk.chunk_index
        child_metadata["content_kind"] = row_block.metadata.get("content_kind", "table_row")
        child_metadata["row_index"] = row_block.metadata.get("row_index")
        child_text = _render_table_row_chunk(caption_text, child_metadata.get("table_headers", []), row_block.text)
        chunks.append(
            ChunkDraft(
                chunk_index=next_index,
                content=child_text,
                token_count=_token_count(child_text),
                metadata=child_metadata,
                parent_block_id=parent_block_id,
                chunk_role="child",
                page_number=row_block.page_number,
                chunk_type=row_block.block_type,
                section_title=group["section_title"],
                subsection_title=group["subsection_title"],
                section_path=list(group["section_path"]),
                block_order_start=row_block.order_index,
                block_order_end=row_block.order_index,
            )
        )
        next_index += 1
    return chunks, next_index


def _build_equation_chunks(
    group: dict[str, Any],
    *,
    base_metadata: dict[str, Any],
    next_index: int,
) -> tuple[list[ChunkDraft], int]:
    blocks = group["blocks"]
    equation_blocks = [block for block in blocks if block.block_type == "equation"]
    explanation_blocks = [block for block in blocks if block.block_type == "equation_explanation"]
    equation_text = "\n".join(block.text.strip() for block in equation_blocks if block.text.strip())
    explanation_text = "\n".join(block.text.strip() for block in explanation_blocks if block.text.strip())
    parent_text = "\n\n".join(part for part in [equation_text, explanation_text] if part).strip()
    if not parent_text:
        return [], next_index
    common_metadata = _common_chunk_metadata(group, base_metadata)
    common_metadata["content_kind"] = "equation_group"
    common_metadata["equation_label"] = next((block.metadata.get("equation_label") for block in equation_blocks if block.metadata.get("equation_label")), None)
    common_metadata["equation_id"] = _structure_group_id(equation_blocks[0] if equation_blocks else explanation_blocks[0])
    parent_block_id = group["parent_block_id"]
    parent_chunk = ChunkDraft(
        chunk_index=next_index,
        content=parent_text,
        token_count=_token_count(parent_text),
        metadata=dict(common_metadata),
        parent_block_id=parent_block_id,
        chunk_role="parent",
        page_number=group["page_number"],
        chunk_type="equation",
        section_title=group["section_title"],
        subsection_title=group["subsection_title"],
        section_path=list(group["section_path"]),
        block_order_start=group["block_order_start"],
        block_order_end=group["block_order_end"],
    )
    chunks = [parent_chunk]
    next_index += 1

    for content_kind, child_text in [("equation", equation_text), ("equation_explanation", parent_text if explanation_text else equation_text)]:
        if not child_text:
            continue
        child_metadata = dict(common_metadata)
        child_metadata["parent_chunk_index"] = parent_chunk.chunk_index
        child_metadata["content_kind"] = content_kind
        chunks.append(
            ChunkDraft(
                chunk_index=next_index,
                content=child_text,
                token_count=_token_count(child_text),
                metadata=child_metadata,
                parent_block_id=parent_block_id,
                chunk_role="child",
                page_number=group["page_number"],
                chunk_type=content_kind,
                section_title=group["section_title"],
                subsection_title=group["subsection_title"],
                section_path=list(group["section_path"]),
                block_order_start=group["block_order_start"],
                block_order_end=group["block_order_end"],
            )
        )
        next_index += 1
    return chunks, next_index


def _build_algorithm_chunks(
    group: dict[str, Any],
    *,
    base_metadata: dict[str, Any],
    splitter: RecursiveCharacterTextSplitter,
    chunk_size: int,
    next_index: int,
) -> tuple[list[ChunkDraft], int]:
    chunks, next_index = _build_prose_chunks(
        group,
        base_metadata=base_metadata,
        splitter=splitter,
        chunk_size=chunk_size,
        next_index=next_index,
    )
    for chunk in chunks:
        chunk.chunk_type = "algorithm"
        chunk.metadata["content_kind"] = "algorithm"
        first_block = group["blocks"][0]
        chunk.metadata["algorithm_label"] = first_block.metadata.get("algorithm_label")
        chunk.metadata["algorithm_id"] = _structure_group_id(first_block)
    return chunks, next_index


def _build_caption_chunks(
    group: dict[str, Any],
    *,
    base_metadata: dict[str, Any],
    next_index: int,
) -> tuple[list[ChunkDraft], int]:
    parent_text = _render_group_text(group)
    if not parent_text:
        return [], next_index
    common_metadata = _common_chunk_metadata(group, base_metadata)
    common_metadata["content_kind"] = "figure_caption"
    first_block = group["blocks"][0]
    common_metadata["caption_label"] = first_block.metadata.get("caption_label")
    common_metadata["related_caption_id"] = _structure_group_id(first_block)
    parent_block_id = group["parent_block_id"]
    parent_chunk = ChunkDraft(
        chunk_index=next_index,
        content=parent_text,
        token_count=_token_count(parent_text),
        metadata=dict(common_metadata),
        parent_block_id=parent_block_id,
        chunk_role="parent",
        page_number=group["page_number"],
        chunk_type="figure_caption",
        section_title=group["section_title"],
        subsection_title=group["subsection_title"],
        section_path=list(group["section_path"]),
        block_order_start=group["block_order_start"],
        block_order_end=group["block_order_end"],
    )
    child_metadata = dict(common_metadata)
    child_metadata["parent_chunk_index"] = parent_chunk.chunk_index
    child_chunk = ChunkDraft(
        chunk_index=next_index + 1,
        content=parent_text,
        token_count=_token_count(parent_text),
        metadata=child_metadata,
        parent_block_id=parent_block_id,
        chunk_role="child",
        page_number=group["page_number"],
        chunk_type="figure_caption",
        section_title=group["section_title"],
        subsection_title=group["subsection_title"],
        section_path=list(group["section_path"]),
        block_order_start=group["block_order_start"],
        block_order_end=group["block_order_end"],
    )
    return [parent_chunk, child_chunk], next_index + 2


def _common_chunk_metadata(group: dict[str, Any], base_metadata: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(base_metadata)
    metadata.update(
        {
            "section_path": list(group["section_path"]),
            "section_title": group["section_title"],
            "subsection_title": group["subsection_title"],
            "chunk_type": group["chunk_type"],
            "page_number": group["page_number"],
            "content_kind": group.get("content_kind", group["chunk_type"]),
        }
    )
    if group.get("structure_group_id"):
        metadata["structure_group_id"] = group["structure_group_id"]
    return metadata


def _structure_group_id(block: ExtractedBlock) -> str | None:
    for key in ("table_id", "equation_id", "algorithm_id", "related_caption_id"):
        value = block.metadata.get(key)
        if value:
            return str(value)
    return None


def _group_chunk_type(block: ExtractedBlock) -> str:
    content_kind = block.metadata.get("content_kind")
    if content_kind in {"table_caption", "table_row"}:
        return "table"
    if content_kind in {"equation", "equation_explanation"}:
        return "equation"
    return block.block_type


def _merged_table_headers(row_blocks: list[ExtractedBlock]) -> list[str]:
    headers: list[str] = []
    for block in row_blocks:
        for header in block.metadata.get("table_headers", []) or []:
            if header not in headers:
                headers.append(header)
    return headers


def _render_table_row_chunk(caption_text: str, headers: list[str], row_text: str) -> str:
    parts = [caption_text.strip()]
    if headers:
        parts.append(f"Headers: {', '.join(headers)}")
    parts.append(f"Row: {row_text.strip()}")
    return "\n".join(part for part in parts if part).strip()
