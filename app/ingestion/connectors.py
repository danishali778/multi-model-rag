from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ConnectorDocumentChange:
    source_id: str
    operation: str
    metadata: dict[str, Any]


class BaseConnector(ABC):
    connector_type: str

    @abstractmethod
    async def list_changes(self, checkpoint: dict[str, Any] | None) -> tuple[list[ConnectorDocumentChange], dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_document(self, source_id: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def fetch_acl(self, source_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def ack_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        raise NotImplementedError
