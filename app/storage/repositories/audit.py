from __future__ import annotations

import json

from app.core.config import Settings
from app.security.pii import redact_payload
from app.storage.db.session import Database
from app.storage.models.audit import AuditLogInput


class AuditRepository:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def record_audit_log(self, payload: AuditLogInput) -> None:
        query = """
            insert into audit_logs (workspace_id, actor_id, event_type, details)
            values (%s, %s, %s, %s::jsonb)
        """
        safe_details = redact_payload(payload.details)
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (payload.workspace_id, payload.actor_id, payload.event_type, json.dumps(safe_details)),
                )
                await conn.commit()
