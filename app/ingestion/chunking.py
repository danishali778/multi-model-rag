from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.domain.entities.rag import ExtractedBlock, ExtractedDocument


@dataclass(slots=True)
class ChunkDraft:
    chunk_index: int
    content: str
    token_count: int
    metadata: dict[str, Any]
    id: UUID = field(default_factory=uuid4)
    parent_block_id: Any | None = None
    chunk_role: str = "child"
    page_number: int | None = None
    chunk_type: str | None = None
    section_title: str | None = None
    subsection_title: str | None = None
    section_path: list[str] | None = None
    block_order_start: int | None = None
    block_order_end: int | None = None
    node_id: UUID | None = None
    parent_node_id: UUID | None = None
    previous_chunk_id: UUID | None = None
    next_chunk_id: UUID | None = None
    level: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    embedding_text: str | None = None


@dataclass(slots=True)
class StructureNodeDraft:
    node_type: str
    node_key: str
    title: str | None
    section_path: list[str]
    level: int
    page_start: int | None
    page_end: int | None
    block_order_start: int
    block_order_end: int
    parent_node_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)


@dataclass(slots=True)
class StructureEdgeDraft:
    from_node_id: UUID
    to_node_id: UUID
    edge_type: str
    edge_order: int
    metadata: dict[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)


@dataclass(slots=True)
class ChunkBuildResult:
    chunks: list[ChunkDraft]
    nodes: list[StructureNodeDraft]
    edges: list[StructureEdgeDraft]


@dataclass(slots=True)
class _ContentNodeBinding:
    group: dict[str, Any]
    node: StructureNodeDraft


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
    chunking_version: str | None = None,
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
        chunking_version=chunking_version,
    )


def chunk_document(
    document: ExtractedDocument,
    *,
    chunk_size: int,
    chunk_overlap: int,
    base_metadata: dict[str, Any] | None = None,
    chunking_version: str | None = None,
) -> list[ChunkDraft]:
    return chunk_document_graph(
        document=document,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        base_metadata=base_metadata,
        chunking_version=chunking_version,
    ).chunks


def chunk_document_graph(
    document: ExtractedDocument,
    *,
    chunk_size: int,
    chunk_overlap: int,
    base_metadata: dict[str, Any] | None = None,
    chunking_version: str | None = None,
) -> ChunkBuildResult:
    if chunking_version == "hybrid-graph-v1":
        return _build_hybrid_graph_chunks(
            document=document,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            base_metadata=base_metadata,
        )
    return ChunkBuildResult(
        chunks=_build_legacy_chunks(
            document=document,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            base_metadata=base_metadata,
        ),
        nodes=[],
        edges=[],
    )


def _build_legacy_chunks(
    *,
    document: ExtractedDocument,
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
        built_chunks, next_index = _build_group_chunks_legacy(
            group=group,
            base_metadata=metadata,
            splitter=splitter,
            chunk_size=chunk_size,
            next_index=next_index,
        )
        chunks.extend(built_chunks)
    return chunks


def _build_hybrid_graph_chunks(
    *,
    document: ExtractedDocument,
    chunk_size: int,
    chunk_overlap: int,
    base_metadata: dict[str, Any] | None = None,
) -> ChunkBuildResult:
    groups = _build_groups(document.blocks)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    metadata = dict(base_metadata or {})
    metadata["chunking_version"] = "hybrid-graph-v1"

    section_nodes, content_bindings, edges = _build_structure_graph(document.blocks, groups)
    all_nodes = sorted(
        [*section_nodes, *(binding.node for binding in content_bindings)],
        key=lambda item: (item.block_order_start, 0 if item.node_type == "section" else 1, item.level, item.node_key),
    )
    blocks_by_order = sorted(document.blocks, key=lambda item: item.order_index)

    chunks: list[ChunkDraft] = []
    next_index = 0
    section_node_ids_emitted: set[UUID] = set()
    binding_by_node_id = {binding.node.id: binding for binding in content_bindings}

    for node in all_nodes:
        if node.node_type == "section":
            section_chunk = _build_section_summary_chunk(
                node=node,
                blocks=blocks_by_order,
                base_metadata=metadata,
                chunk_index=next_index,
                title=document.title,
            )
            if section_chunk is not None:
                chunks.append(section_chunk)
                next_index += 1
                section_node_ids_emitted.add(node.id)
            continue

        binding = binding_by_node_id[node.id]
        built_chunks, next_index = _build_graph_node_chunks(
            node=node,
            group=binding.group,
            base_metadata=metadata,
            splitter=splitter,
            chunk_size=chunk_size,
            next_index=next_index,
            title=document.title,
        )
        chunks.extend(built_chunks)

    _link_graph_child_chunks(chunks)
    return ChunkBuildResult(
        chunks=chunks,
        nodes=all_nodes,
        edges=edges,
    )


def _build_structure_graph(
    blocks: list[ExtractedBlock],
    groups: list[dict[str, Any]],
) -> tuple[list[StructureNodeDraft], list[_ContentNodeBinding], list[StructureEdgeDraft]]:
    section_nodes_by_path: dict[tuple[str, ...], StructureNodeDraft] = {}
    section_nodes: list[StructureNodeDraft] = []
    content_bindings: list[_ContentNodeBinding] = []
    edges: list[StructureEdgeDraft] = []
    heading_block_ids: dict[tuple[str, ...], UUID] = {}

    def ensure_section_path(path: list[str], block: ExtractedBlock) -> UUID | None:
        parent_id: UUID | None = None
        for level, part in enumerate(path, start=1):
            prefix = tuple(path[:level])
            node = section_nodes_by_path.get(prefix)
            if node is None:
                node = StructureNodeDraft(
                    node_type="section",
                    node_key=f"section:{' > '.join(prefix)}",
                    title=part,
                    section_path=list(prefix),
                    level=level,
                    page_start=block.page_number,
                    page_end=block.page_number,
                    block_order_start=block.order_index,
                    block_order_end=block.order_index,
                    parent_node_id=parent_id,
                    metadata={
                        "section_title": prefix[0] if prefix else None,
                        "subsection_title": prefix[-1] if len(prefix) > 1 else None,
                    },
                )
                section_nodes_by_path[prefix] = node
                section_nodes.append(node)
                if parent_id is not None:
                    edges.append(
                        StructureEdgeDraft(
                            from_node_id=parent_id,
                            to_node_id=node.id,
                            edge_type="parent_child",
                            edge_order=node.block_order_start,
                        )
                    )
            _touch_node_range(
                node=node,
                page_start=block.page_number,
                page_end=block.page_number,
                order_start=block.order_index,
                order_end=block.order_index,
            )
            parent_id = node.id
        return parent_id

    for block in sorted(blocks, key=lambda item: item.order_index):
        if block.block_type != "heading" or not block.section_path:
            continue
        ensure_section_path(block.section_path, block)
        section_node = section_nodes_by_path[tuple(block.section_path)]
        section_node.title = block.section_path[-1]
        section_node.level = block.heading_level or len(block.section_path)
        section_node.metadata["heading_block_id"] = str(block.id)
        heading_block_ids[tuple(block.section_path)] = block.id

    for group in groups:
        first_block = group["blocks"][0]
        parent_section_id = ensure_section_path(group["section_path"], first_block)
        structure_group_id = group.get("structure_group_id")
        node_type = _node_type_for_group(group)
        node = StructureNodeDraft(
            node_type=node_type,
            node_key=str(structure_group_id or f"{node_type}:{group['block_order_start']}:{group['block_order_end']}"),
            title=_node_title_for_group(group),
            section_path=list(group["section_path"]),
            level=len(group["section_path"]) + 1 if group["section_path"] else 1,
            page_start=_group_page_start(group),
            page_end=_group_page_end(group),
            block_order_start=group["block_order_start"],
            block_order_end=group["block_order_end"],
            parent_node_id=parent_section_id,
            metadata={
                "content_kind": group.get("content_kind", group["chunk_type"]),
                "structure_group_id": structure_group_id,
                "section_title": group["section_title"],
                "subsection_title": group["subsection_title"],
            },
        )
        if node_type == "table":
            caption_block = next((block for block in group["blocks"] if block.block_type == "table_caption"), None)
            node.metadata["caption_label"] = caption_block.metadata.get("caption_label") if caption_block else None
        if node_type == "equation_group":
            equation_block = next((block for block in group["blocks"] if block.block_type == "equation"), None)
            node.metadata["equation_label"] = equation_block.metadata.get("equation_label") if equation_block else None
        if node_type == "algorithm":
            node.metadata["algorithm_label"] = group["blocks"][0].metadata.get("algorithm_label")
        if node_type == "figure_caption":
            node.metadata["caption_label"] = group["blocks"][0].metadata.get("caption_label")

        content_bindings.append(_ContentNodeBinding(group=group, node=node))
        if parent_section_id is not None:
            edges.append(
                StructureEdgeDraft(
                    from_node_id=parent_section_id,
                    to_node_id=node.id,
                    edge_type="parent_child",
                    edge_order=node.block_order_start,
                )
            )
        _touch_section_ancestors(section_nodes_by_path, group["section_path"], node)

    children_by_parent: dict[UUID | None, list[StructureNodeDraft]] = defaultdict(list)
    for node in [*section_nodes, *(binding.node for binding in content_bindings)]:
        children_by_parent[node.parent_node_id].append(node)

    for siblings in children_by_parent.values():
        ordered = sorted(siblings, key=lambda item: (item.block_order_start, item.level, item.node_key))
        for left, right in zip(ordered, ordered[1:], strict=False):
            edges.append(
                StructureEdgeDraft(
                    from_node_id=left.id,
                    to_node_id=right.id,
                    edge_type="next_sibling",
                    edge_order=right.block_order_start,
                )
            )
            edges.append(
                StructureEdgeDraft(
                    from_node_id=right.id,
                    to_node_id=left.id,
                    edge_type="previous_sibling",
                    edge_order=left.block_order_start,
                )
            )

    for path, heading_id in heading_block_ids.items():
        node = section_nodes_by_path.get(path)
        if node is not None:
            node.metadata["heading_block_id"] = str(heading_id)

    return section_nodes, content_bindings, edges


def _build_section_summary_chunk(
    *,
    node: StructureNodeDraft,
    blocks: list[ExtractedBlock],
    base_metadata: dict[str, Any],
    chunk_index: int,
    title: str | None,
) -> ChunkDraft | None:
    summary_text = _render_section_summary(node, blocks)
    if not summary_text.strip():
        return None
    metadata = _common_graph_metadata(node, base_metadata)
    metadata["content_kind"] = "section_summary"
    metadata["node_type"] = "section"
    heading_block_id = node.metadata.get("heading_block_id")
    chunk = ChunkDraft(
        chunk_index=chunk_index,
        content=summary_text,
        token_count=_token_count(summary_text),
        metadata=metadata,
        parent_block_id=UUID(heading_block_id) if isinstance(heading_block_id, str) else None,
        chunk_role="parent",
        page_number=node.page_start,
        chunk_type="section",
        section_title=node.section_path[0] if node.section_path else node.title,
        subsection_title=node.section_path[-1] if len(node.section_path) > 1 else None,
        section_path=list(node.section_path),
        block_order_start=node.block_order_start,
        block_order_end=node.block_order_end,
        node_id=node.id,
        parent_node_id=node.parent_node_id,
        level=node.level,
        page_start=node.page_start,
        page_end=node.page_end,
    )
    chunk.embedding_text = _build_embedding_text(title=title, node_type="section", chunk=chunk)
    return chunk


def _build_graph_node_chunks(
    *,
    node: StructureNodeDraft,
    group: dict[str, Any],
    base_metadata: dict[str, Any],
    splitter: RecursiveCharacterTextSplitter,
    chunk_size: int,
    next_index: int,
    title: str | None,
) -> tuple[list[ChunkDraft], int]:
    content_kind = str(node.metadata.get("content_kind") or group.get("content_kind") or "")
    if content_kind in {"table_caption", "table_row"}:
        chunks, next_index = _build_table_chunks_graph(
            node=node,
            group=group,
            base_metadata=base_metadata,
            next_index=next_index,
            title=title,
        )
    elif content_kind in {"equation", "equation_explanation"}:
        chunks, next_index = _build_equation_chunks_graph(
            node=node,
            group=group,
            base_metadata=base_metadata,
            next_index=next_index,
            title=title,
        )
    elif content_kind == "algorithm":
        chunks, next_index = _build_algorithm_chunks_graph(
            node=node,
            group=group,
            base_metadata=base_metadata,
            splitter=splitter,
            chunk_size=chunk_size,
            next_index=next_index,
            title=title,
        )
    elif content_kind == "figure_caption":
        chunks, next_index = _build_caption_chunks_graph(
            node=node,
            group=group,
            base_metadata=base_metadata,
            next_index=next_index,
            title=title,
        )
    else:
        chunks, next_index = _build_prose_chunks_graph(
            node=node,
            group=group,
            base_metadata=base_metadata,
            splitter=splitter,
            chunk_size=chunk_size,
            next_index=next_index,
            title=title,
        )
    return chunks, next_index


def _build_groups(blocks: list[ExtractedBlock]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for block in sorted(blocks, key=lambda item: item.order_index):
        if block.metadata.get("exclude_from_chunking"):
            continue
        if block.block_type == "heading":
            current = None
            continue
        structure_group_id = _structure_group_id(block)
        if structure_group_id is None and block.metadata.get("content_kind") == "audio_transcript_segment":
            structure_group_id = f"audio-segment:{block.order_index}"
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


def _build_group_chunks_legacy(
    *,
    group: dict[str, Any],
    base_metadata: dict[str, Any],
    splitter: RecursiveCharacterTextSplitter,
    chunk_size: int,
    next_index: int,
) -> tuple[list[ChunkDraft], int]:
    content_kind = group.get("content_kind")
    if content_kind in {"table_caption", "table_row"}:
        return _build_table_chunks_legacy(group, base_metadata=base_metadata, next_index=next_index)
    if content_kind in {"equation", "equation_explanation"}:
        return _build_equation_chunks_legacy(group, base_metadata=base_metadata, next_index=next_index)
    if content_kind == "algorithm":
        return _build_algorithm_chunks_legacy(
            group,
            base_metadata=base_metadata,
            splitter=splitter,
            chunk_size=chunk_size,
            next_index=next_index,
        )
    if content_kind == "figure_caption":
        return _build_caption_chunks_legacy(group, base_metadata=base_metadata, next_index=next_index)
    return _build_prose_chunks_legacy(
        group,
        base_metadata=base_metadata,
        splitter=splitter,
        chunk_size=chunk_size,
        next_index=next_index,
    )


def _build_prose_chunks_legacy(
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
    _apply_audio_segment_metadata(group, common_metadata)
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
    if parent_chunk.token_count >= chunk_size:
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


def _build_prose_chunks_graph(
    *,
    node: StructureNodeDraft,
    group: dict[str, Any],
    base_metadata: dict[str, Any],
    splitter: RecursiveCharacterTextSplitter,
    chunk_size: int,
    next_index: int,
    title: str | None,
) -> tuple[list[ChunkDraft], int]:
    parent_text = _render_group_text(group)
    if not parent_text.strip():
        return [], next_index
    common_metadata = _common_graph_metadata(node, base_metadata)
    _apply_audio_segment_metadata(group, common_metadata)
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
        node_id=node.id,
        parent_node_id=node.parent_node_id,
        level=node.level,
        page_start=node.page_start,
        page_end=node.page_end,
    )
    parent_chunk.embedding_text = _build_embedding_text(title=title, node_type=node.node_type, chunk=parent_chunk)
    chunks = [parent_chunk]
    next_index += 1

    child_parts = [parent_text]
    if parent_chunk.token_count >= chunk_size:
        child_parts = splitter.split_text(parent_text)

    for part in child_parts:
        child_metadata = dict(common_metadata)
        child_metadata["parent_chunk_index"] = parent_chunk.chunk_index
        child_chunk = ChunkDraft(
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
            node_id=node.id,
            parent_node_id=node.parent_node_id,
            level=node.level,
            page_start=node.page_start,
            page_end=node.page_end,
        )
        child_chunk.embedding_text = _build_embedding_text(title=title, node_type=node.node_type, chunk=child_chunk)
        chunks.append(child_chunk)
        next_index += 1
    return chunks, next_index


def _build_table_chunks_legacy(
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
    common_metadata["table_parse_status"] = (
        caption_block.metadata.get("table_parse_status")
        if caption_block
        else (row_blocks[0].metadata.get("table_parse_status") if row_blocks else None)
    )
    common_metadata["docling_table_shape"] = (
        caption_block.metadata.get("docling_table_shape")
        if caption_block
        else (row_blocks[0].metadata.get("docling_table_shape") if row_blocks else None)
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
        child_metadata["table_parse_status"] = row_block.metadata.get(
            "table_parse_status",
            common_metadata.get("table_parse_status"),
        )
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


def _build_table_chunks_graph(
    *,
    node: StructureNodeDraft,
    group: dict[str, Any],
    base_metadata: dict[str, Any],
    next_index: int,
    title: str | None,
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

    common_metadata = _common_graph_metadata(node, base_metadata)
    common_metadata["content_kind"] = "table"
    common_metadata["caption_label"] = caption_block.metadata.get("caption_label") if caption_block else None
    common_metadata["table_id"] = _structure_group_id(caption_block or row_blocks[0])
    common_metadata["table_headers"] = _merged_table_headers(row_blocks)
    common_metadata["table_parse_status"] = (
        caption_block.metadata.get("table_parse_status")
        if caption_block
        else (row_blocks[0].metadata.get("table_parse_status") if row_blocks else None)
    )
    common_metadata["docling_table_shape"] = (
        caption_block.metadata.get("docling_table_shape")
        if caption_block
        else (row_blocks[0].metadata.get("docling_table_shape") if row_blocks else None)
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
        chunk_type="table",
        section_title=group["section_title"],
        subsection_title=group["subsection_title"],
        section_path=list(group["section_path"]),
        block_order_start=group["block_order_start"],
        block_order_end=group["block_order_end"],
        node_id=node.id,
        parent_node_id=node.parent_node_id,
        level=node.level,
        page_start=node.page_start,
        page_end=node.page_end,
    )
    parent_chunk.embedding_text = _build_embedding_text(title=title, node_type=node.node_type, chunk=parent_chunk)
    chunks = [parent_chunk]
    next_index += 1

    for row_block in row_blocks or ([caption_block] if caption_block else []):
        child_metadata = dict(common_metadata)
        child_metadata["parent_chunk_index"] = parent_chunk.chunk_index
        child_metadata["content_kind"] = row_block.metadata.get("content_kind", "table_row")
        child_metadata["row_index"] = row_block.metadata.get("row_index")
        child_metadata["table_parse_status"] = row_block.metadata.get(
            "table_parse_status",
            common_metadata.get("table_parse_status"),
        )
        child_text = _render_table_row_chunk(caption_text, child_metadata.get("table_headers", []), row_block.text)
        child_chunk = ChunkDraft(
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
            node_id=node.id,
            parent_node_id=node.parent_node_id,
            level=node.level,
            page_start=node.page_start,
            page_end=node.page_end,
        )
        child_chunk.embedding_text = _build_embedding_text(title=title, node_type=node.node_type, chunk=child_chunk)
        chunks.append(child_chunk)
        next_index += 1
    return chunks, next_index


def _build_equation_chunks_legacy(
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


def _build_equation_chunks_graph(
    *,
    node: StructureNodeDraft,
    group: dict[str, Any],
    base_metadata: dict[str, Any],
    next_index: int,
    title: str | None,
) -> tuple[list[ChunkDraft], int]:
    blocks = group["blocks"]
    equation_blocks = [block for block in blocks if block.block_type == "equation"]
    explanation_blocks = [block for block in blocks if block.block_type == "equation_explanation"]
    equation_text = "\n".join(block.text.strip() for block in equation_blocks if block.text.strip())
    explanation_text = "\n".join(block.text.strip() for block in explanation_blocks if block.text.strip())
    parent_text = "\n\n".join(part for part in [equation_text, explanation_text] if part).strip()
    if not parent_text:
        return [], next_index
    common_metadata = _common_graph_metadata(node, base_metadata)
    common_metadata["content_kind"] = "equation_group"
    common_metadata["equation_label"] = next(
        (block.metadata.get("equation_label") for block in equation_blocks if block.metadata.get("equation_label")),
        None,
    )
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
        node_id=node.id,
        parent_node_id=node.parent_node_id,
        level=node.level,
        page_start=node.page_start,
        page_end=node.page_end,
    )
    parent_chunk.embedding_text = _build_embedding_text(title=title, node_type=node.node_type, chunk=parent_chunk)
    chunks = [parent_chunk]
    next_index += 1

    for child_kind, child_text in [("equation", equation_text), ("equation_explanation", explanation_text or equation_text)]:
        if not child_text:
            continue
        child_metadata = dict(common_metadata)
        child_metadata["parent_chunk_index"] = parent_chunk.chunk_index
        child_metadata["content_kind"] = child_kind
        child_chunk = ChunkDraft(
            chunk_index=next_index,
            content=child_text,
            token_count=_token_count(child_text),
            metadata=child_metadata,
            parent_block_id=parent_block_id,
            chunk_role="child",
            page_number=group["page_number"],
            chunk_type=child_kind,
            section_title=group["section_title"],
            subsection_title=group["subsection_title"],
            section_path=list(group["section_path"]),
            block_order_start=group["block_order_start"],
            block_order_end=group["block_order_end"],
            node_id=node.id,
            parent_node_id=node.parent_node_id,
            level=node.level,
            page_start=node.page_start,
            page_end=node.page_end,
        )
        child_chunk.embedding_text = _build_embedding_text(title=title, node_type=node.node_type, chunk=child_chunk)
        chunks.append(child_chunk)
        next_index += 1
    return chunks, next_index


def _build_algorithm_chunks_legacy(
    group: dict[str, Any],
    *,
    base_metadata: dict[str, Any],
    splitter: RecursiveCharacterTextSplitter,
    chunk_size: int,
    next_index: int,
) -> tuple[list[ChunkDraft], int]:
    chunks, next_index = _build_prose_chunks_legacy(
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


def _build_algorithm_chunks_graph(
    *,
    node: StructureNodeDraft,
    group: dict[str, Any],
    base_metadata: dict[str, Any],
    splitter: RecursiveCharacterTextSplitter,
    chunk_size: int,
    next_index: int,
    title: str | None,
) -> tuple[list[ChunkDraft], int]:
    chunks, next_index = _build_prose_chunks_graph(
        node=node,
        group=group,
        base_metadata=base_metadata,
        splitter=splitter,
        chunk_size=chunk_size,
        next_index=next_index,
        title=title,
    )
    for chunk in chunks:
        chunk.chunk_type = "algorithm"
        chunk.metadata["content_kind"] = "algorithm"
        first_block = group["blocks"][0]
        chunk.metadata["algorithm_label"] = first_block.metadata.get("algorithm_label")
        chunk.metadata["algorithm_id"] = _structure_group_id(first_block)
        chunk.embedding_text = _build_embedding_text(title=title, node_type=node.node_type, chunk=chunk)
    return chunks, next_index


def _build_caption_chunks_legacy(
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


def _build_caption_chunks_graph(
    *,
    node: StructureNodeDraft,
    group: dict[str, Any],
    base_metadata: dict[str, Any],
    next_index: int,
    title: str | None,
) -> tuple[list[ChunkDraft], int]:
    parent_text = _render_group_text(group)
    if not parent_text:
        return [], next_index
    common_metadata = _common_graph_metadata(node, base_metadata)
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
        node_id=node.id,
        parent_node_id=node.parent_node_id,
        level=node.level,
        page_start=node.page_start,
        page_end=node.page_end,
    )
    parent_chunk.embedding_text = _build_embedding_text(title=title, node_type=node.node_type, chunk=parent_chunk)
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
        node_id=node.id,
        parent_node_id=node.parent_node_id,
        level=node.level,
        page_start=node.page_start,
        page_end=node.page_end,
    )
    child_chunk.embedding_text = _build_embedding_text(title=title, node_type=node.node_type, chunk=child_chunk)
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


def _common_graph_metadata(node: StructureNodeDraft, base_metadata: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(base_metadata)
    metadata.update(
        {
            "section_path": list(node.section_path),
            "section_title": node.section_path[0] if node.section_path else node.title,
            "subsection_title": node.section_path[-1] if len(node.section_path) > 1 else None,
            "node_id": str(node.id),
            "parent_node_id": str(node.parent_node_id) if node.parent_node_id else None,
            "node_type": node.node_type,
            "node_key": node.node_key,
            "level": node.level,
            "page_start": node.page_start,
            "page_end": node.page_end,
            "content_kind": node.metadata.get("content_kind", node.node_type),
        }
    )
    structure_group_id = node.metadata.get("structure_group_id")
    if structure_group_id:
        metadata["structure_group_id"] = structure_group_id
    return metadata


def _structure_group_id(block: ExtractedBlock) -> str | None:
    for key in ("table_id", "equation_id", "algorithm_id", "related_caption_id", "audio_segment_id"):
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


def _node_type_for_group(group: dict[str, Any]) -> str:
    content_kind = str(group.get("content_kind") or group.get("chunk_type") or "")
    if content_kind in {"table_caption", "table_row"}:
        return "table"
    if content_kind in {"equation", "equation_explanation"}:
        return "equation_group"
    if content_kind == "algorithm":
        return "algorithm"
    if content_kind == "figure_caption":
        return "figure_caption"
    return "prose_group"


def _node_title_for_group(group: dict[str, Any]) -> str | None:
    content_kind = _node_type_for_group(group)
    if content_kind == "table":
        caption = next((block.text.strip() for block in group["blocks"] if block.block_type == "table_caption"), None)
        return caption or "Table"
    if content_kind == "equation_group":
        label = next((block.metadata.get("equation_label") for block in group["blocks"] if block.metadata.get("equation_label")), None)
        return f"Equation {label}" if label else "Equation"
    if content_kind == "algorithm":
        label = group["blocks"][0].metadata.get("algorithm_label")
        return str(label) if label else "Algorithm"
    if content_kind == "figure_caption":
        return group["blocks"][0].text.strip()
    return group["subsection_title"] or group["section_title"]


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


def _render_section_summary(node: StructureNodeDraft, blocks: list[ExtractedBlock]) -> str:
    prefix = node.section_path
    snippets: list[str] = [f"Section: {' > '.join(prefix) if prefix else (node.title or 'Section')}"]
    char_budget = 900
    current_chars = sum(len(part) for part in snippets)
    for block in blocks:
        if block.order_index < node.block_order_start or block.order_index > node.block_order_end:
            continue
        if len(block.section_path) < len(prefix) or block.section_path[: len(prefix)] != prefix:
            continue
        if block.block_type == "heading":
            continue
        text = block.text.strip()
        if not text:
            continue
        rendered = f"- {text}" if block.block_type == "list_item" else text
        if current_chars + len(rendered) > char_budget and len(snippets) > 1:
            break
        snippets.append(rendered)
        current_chars += len(rendered)
        if len(snippets) >= 4:
            break
    return "\n\n".join(snippets).strip()


def _build_embedding_text(*, title: str | None, node_type: str, chunk: ChunkDraft) -> str:
    doc_title = title or chunk.metadata.get("title") or "Document"
    section_path = " > ".join(chunk.section_path or [])
    lines = [f"Document: {doc_title}"]
    if section_path:
        lines.append(f"Section Path: {section_path}")
    lines.append(f"Node Type: {node_type}")
    if chunk.metadata.get("content_kind") == "audio_transcript_segment":
        start_ms = chunk.metadata.get("start_ms")
        end_ms = chunk.metadata.get("end_ms")
        speaker_label = chunk.metadata.get("speaker_label")
        if start_ms is not None or end_ms is not None:
            lines.append(f"Transcript Timing: {start_ms or 0}ms to {end_ms or 'unknown'}ms")
        if speaker_label:
            lines.append(f"Speaker: {speaker_label}")
    if chunk.metadata.get("caption_label"):
        lines.append(f"Table: {chunk.metadata['caption_label']}")
    if chunk.metadata.get("table_headers"):
        lines.append(f"Headers: {', '.join(chunk.metadata['table_headers'])}")
    if chunk.metadata.get("equation_label"):
        lines.append(f"Equation Label: {chunk.metadata['equation_label']}")
    if chunk.metadata.get("algorithm_label"):
        lines.append(f"Algorithm Label: {chunk.metadata['algorithm_label']}")
    lines.append(f"Content: {chunk.content}")
    return "\n".join(line for line in lines if line).strip()


def _apply_audio_segment_metadata(group: dict[str, Any], metadata: dict[str, Any]) -> None:
    if group.get("content_kind") != "audio_transcript_segment":
        return
    first_block = group["blocks"][0]
    for key in ("audio_segment_id", "segment_index", "start_ms", "end_ms", "speaker_label", "segment_confidence"):
        if key in first_block.metadata:
            metadata[key] = first_block.metadata[key]


def _link_graph_child_chunks(chunks: list[ChunkDraft]) -> None:
    children = sorted(
        [chunk for chunk in chunks if chunk.chunk_role == "child"],
        key=lambda item: (
            item.page_start if item.page_start is not None else item.page_number if item.page_number is not None else -1,
            item.block_order_start if item.block_order_start is not None else -1,
            item.chunk_index,
        ),
    )
    for index, chunk in enumerate(children):
        chunk.previous_chunk_id = children[index - 1].id if index > 0 else None
        chunk.next_chunk_id = children[index + 1].id if index + 1 < len(children) else None
        chunk.metadata["previous_chunk_id"] = str(chunk.previous_chunk_id) if chunk.previous_chunk_id else None
        chunk.metadata["next_chunk_id"] = str(chunk.next_chunk_id) if chunk.next_chunk_id else None


def _touch_node_range(
    *,
    node: StructureNodeDraft,
    page_start: int | None,
    page_end: int | None,
    order_start: int,
    order_end: int,
) -> None:
    if node.page_start is None or (page_start is not None and page_start < node.page_start):
        node.page_start = page_start
    if node.page_end is None or (page_end is not None and page_end > node.page_end):
        node.page_end = page_end
    node.block_order_start = min(node.block_order_start, order_start)
    node.block_order_end = max(node.block_order_end, order_end)


def _touch_section_ancestors(
    section_nodes_by_path: dict[tuple[str, ...], StructureNodeDraft],
    section_path: list[str],
    content_node: StructureNodeDraft,
) -> None:
    for level in range(1, len(section_path) + 1):
        node = section_nodes_by_path.get(tuple(section_path[:level]))
        if node is None:
            continue
        _touch_node_range(
            node=node,
            page_start=content_node.page_start,
            page_end=content_node.page_end,
            order_start=content_node.block_order_start,
            order_end=content_node.block_order_end,
        )


def _group_page_start(group: dict[str, Any]) -> int | None:
    pages = [block.page_number for block in group["blocks"] if block.page_number is not None]
    return min(pages) if pages else None


def _group_page_end(group: dict[str, Any]) -> int | None:
    pages = [block.page_number for block in group["blocks"] if block.page_number is not None]
    return max(pages) if pages else None
