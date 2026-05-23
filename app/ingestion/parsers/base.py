from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.domain.entities.rag import ExtractedBlock, ExtractedDocument


class BaseParser(ABC):
    source_type: str

    @abstractmethod
    def parse(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        raise NotImplementedError

    async def parse_async(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        return self.parse(raw_bytes, metadata)

    def default_title(self, metadata: dict) -> str | None:
        filename = metadata.get("filename") or metadata.get("storage_path")
        if not filename:
            return None
        return Path(str(filename)).stem

    def make_block(
        self,
        *,
        block_type: str,
        text: str,
        order_index: int,
        section_path: list[str] | None = None,
        page_number: int | None = None,
        heading_level: int | None = None,
        parent_block_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExtractedBlock:
        return ExtractedBlock(
            id=uuid4(),
            block_type=block_type,
            text=text.strip(),
            page_number=page_number,
            heading_level=heading_level,
            section_path=list(section_path or []),
            order_index=order_index,
            parent_block_id=parent_block_id,
            metadata=dict(metadata or {}),
        )

    def build_document(
        self,
        *,
        title: str | None,
        metadata: dict[str, Any],
        blocks: list[ExtractedBlock],
        warnings: list[str] | None = None,
    ) -> ExtractedDocument:
        filtered = [block for block in blocks if block.text.strip()]
        text = "\n\n".join(block.text.strip() for block in filtered)
        return ExtractedDocument(
            text=text.strip(),
            detected_source_type=self.source_type,
            title=title or self.default_title(metadata),
            metadata={**metadata, "source_type": self.source_type},
            blocks=filtered,
            section_tree=_build_section_tree(filtered),
            warnings=list(warnings or []),
        )


def _build_section_tree(blocks: list[ExtractedBlock]) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    seen_paths: set[tuple[str, ...]] = set()
    for block in blocks:
        if block.block_type != "heading" or not block.section_path:
            continue
        path_key = tuple(block.section_path)
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        current = roots
        for depth, label in enumerate(block.section_path, start=1):
            existing = next((node for node in current if node["title"] == label), None)
            if existing is None:
                existing = {
                    "title": label,
                    "depth": depth,
                    "page_number": block.page_number,
                    "children": [],
                }
                current.append(existing)
            current = existing["children"]
    return roots
