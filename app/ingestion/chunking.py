from dataclasses import dataclass
from typing import Any

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter


@dataclass(slots=True)
class ChunkDraft:
    chunk_index: int
    content: str
    token_count: int
    metadata: dict[str, Any]


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
    base_metadata: dict[str, Any],
) -> list[ChunkDraft]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    parts = splitter.split_text(text)
    chunks: list[ChunkDraft] = []
    for index, part in enumerate(parts):
        metadata = dict(base_metadata)
        metadata["section"] = index
        chunks.append(
            ChunkDraft(
                chunk_index=index,
                content=part,
                token_count=_token_count(part),
                metadata=metadata,
            )
        )
    return chunks
