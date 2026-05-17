from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.domain.entities.rag import ExtractedDocument


class BaseParser(ABC):
    source_type: str

    @abstractmethod
    def parse(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        raise NotImplementedError

    def default_title(self, metadata: dict) -> str | None:
        filename = metadata.get("filename") or metadata.get("storage_path")
        if not filename:
            return None
        return Path(str(filename)).stem
