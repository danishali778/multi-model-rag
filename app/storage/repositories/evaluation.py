from __future__ import annotations

import json
from uuid import UUID

from app.core.config import Settings
from app.storage.db.session import Database
from app.storage.models.evaluation import EvaluationRunCreateInput


class EvaluationRepository:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def create_evaluation_run(self, payload: EvaluationRunCreateInput) -> UUID:
        query = """
            insert into evaluation_runs (workspace_id, run_type, model_profile, metrics, details)
            values (%s, %s, %s, %s::jsonb, %s::jsonb)
            returning id
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        payload.workspace_id,
                        payload.run_type,
                        payload.model_profile,
                        json.dumps(payload.metrics),
                        json.dumps(payload.details),
                    ),
                )
                row = await cur.fetchone()
                await conn.commit()
        return row["id"]
