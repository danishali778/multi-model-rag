from __future__ import annotations

import json

from app.core.config import Settings
from app.storage.db.session import Database
from app.storage.models.usage import ModelUsageInput


class UsageRepository:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def record_model_usage(self, payload: ModelUsageInput) -> None:
        query = """
            insert into model_usage (
                workspace_id, user_id, operation, model_profile, provider, model_name,
                input_tokens, output_tokens, estimated_cost_usd, details
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        payload.workspace_id,
                        payload.user_id,
                        payload.operation,
                        payload.model_profile,
                        payload.provider,
                        payload.model_name,
                        payload.input_tokens,
                        payload.output_tokens,
                        payload.estimated_cost_usd,
                        json.dumps(payload.details),
                    ),
                )
                await conn.commit()
