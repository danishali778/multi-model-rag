from __future__ import annotations

import json

from app.core.config import Settings
from app.storage.db.session import Database
from app.storage.models.connector_sync import ConnectorCheckpointUpsertInput


class ConnectorSyncRepository:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def upsert_connector_checkpoint(self, payload: ConnectorCheckpointUpsertInput) -> None:
        query = """
            insert into connector_sync_states (workspace_id, connector_type, source_key, cursor, status, error_message, last_run_at)
            values (%s, %s, %s, %s::jsonb, %s, %s, now())
            on conflict (workspace_id, connector_type, source_key)
            do update set cursor = excluded.cursor, status = excluded.status, error_message = excluded.error_message, last_run_at = now()
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        payload.workspace_id,
                        payload.connector_type,
                        payload.source_key,
                        json.dumps(payload.cursor),
                        payload.status,
                        payload.error_message,
                    ),
                )
                await conn.commit()
