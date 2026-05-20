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
        parent_text = _render_group_text(group)
        if not parent_text.strip():
            continue
        common_metadata = dict(metadata)
        common_metadata.update(
            {
                "section_path": list(group["section_path"]),
                "section_title": group["section_title"],
                "subsection_title": group["subsection_title"],
                "chunk_type": group["chunk_type"],
                "page_number": group["page_number"],
            }
        )
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
        chunks.append(parent_chunk)
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
    return chunks


def _build_groups(blocks: list[ExtractedBlock]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for block in sorted(blocks, key=lambda item: item.order_index):
        if block.block_type == "heading":
            current = None
            continue
        key = (tuple(block.section_path), block.parent_block_id, block.page_number)
        if current is None or current["key"] != key:
            current = {
                "key": key,
                "parent_block_id": block.parent_block_id or block.id,
                "section_path": list(block.section_path),
                "section_title": block.section_path[0] if block.section_path else None,
                "subsection_title": block.section_path[-1] if len(block.section_path) > 1 else None,
                "page_number": block.page_number,
                "chunk_type": block.block_type,
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
