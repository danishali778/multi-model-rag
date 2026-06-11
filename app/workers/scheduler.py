from __future__ import annotations

from app.domain.entities.rag import ConnectorSyncRequest


class Scheduler:
    async def start(self) -> None:
        return None

    async def enqueue_connector_sync(self, request: ConnectorSyncRequest) -> dict:
        return {
            "workspace_id": str(request.workspace_id),
            "connector_type": request.connector_type,
            "source_key": request.source_key,
            "cursor": request.cursor or {},
        }
