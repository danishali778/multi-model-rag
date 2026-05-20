from __future__ import annotations

import json

from app.core.config import Settings
from app.domain.errors import NotFoundError
from app.storage.db.session import Database
from app.storage.models.feedback import FeedbackCreateInput


class FeedbackRepository:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def create_feedback(self, payload: FeedbackCreateInput):
        query = """
            insert into feedback (workspace_id, conversation_id, message_id, user_id, rating, comments, metadata)
            select c.workspace_id, c.id, m.id, %s, %s, %s, %s::jsonb
            from messages m
            join conversations c on c.id = m.conversation_id
            where c.workspace_id = %s and c.user_id = %s and m.id = %s
            returning id
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        payload.user_id,
                        payload.rating,
                        payload.comments,
                        json.dumps(payload.metadata),
                        payload.workspace_id,
                        payload.user_id,
                        payload.message_id,
                    ),
                )
                row = await cur.fetchone()
                await conn.commit()
        if not row:
            raise NotFoundError("Message not found.")
        return row["id"]
