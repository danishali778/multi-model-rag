from hashlib import sha256
from typing import Any

from app.ingestion.chunking import ChunkDraft, chunk_text


def content_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def content_hash_bytes(raw_bytes: bytes) -> str:
    return sha256(raw_bytes).hexdigest()


def build_chunks(
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    metadata: dict[str, Any],
) -> list[ChunkDraft]:
    return chunk_text(
        text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        base_metadata=metadata,
    )
