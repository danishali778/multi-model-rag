from __future__ import annotations

import json
from uuid import UUID

from app.core.config import Settings
from app.storage.db.session import Database
from app.storage.models.conversation import (
    ConversationCreateInput,
    ConversationMessageRow,
    ConversationRow,
    ConversationSummaryRow,
    MessageCreateInput,
)


class ConversationRepository:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def create_conversation(self, payload: ConversationCreateInput, *, conn=None) -> UUID:
        query = """
            insert into conversations (id, workspace_id, user_id, title)
            values (coalesce(%s, gen_random_uuid()), %s, %s, %s)
            returning id
        """
        if conn is None:
            async with self.db.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, (payload.id, payload.workspace_id, payload.user_id, payload.title))
                    row = await cur.fetchone()
                    await conn.commit()
        else:
            async with conn.cursor() as cur:
                await cur.execute(query, (payload.id, payload.workspace_id, payload.user_id, payload.title))
                row = await cur.fetchone()
        return row["id"]

    async def create_message(self, payload: MessageCreateInput, *, conn=None) -> UUID:
        query = """
            insert into messages (id, conversation_id, role, content, model_profile, sources, token_usage)
            values (coalesce(%s, gen_random_uuid()), %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            returning id
        """
        params = (
            payload.id,
            payload.conversation_id,
            payload.role,
            payload.content,
            payload.model_profile,
            json.dumps(payload.sources),
            json.dumps(payload.token_usage),
        )
        if conn is None:
            async with self.db.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, params)
                    row = await cur.fetchone()
                    await cur.execute(
                        "update conversations set updated_at = now() where id = %s",
                        (payload.conversation_id,),
                    )
                    await conn.commit()
        else:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                row = await cur.fetchone()
                await cur.execute(
                    "update conversations set updated_at = now() where id = %s",
                    (payload.conversation_id,),
                )
        return row["id"]

    async def get_conversation(
        self,
        *,
        workspace_id: UUID,
        conversation_id: UUID,
        user_id: UUID,
    ) -> ConversationRow | None:
        query = """
            select id, title, created_at, updated_at
            from conversations
            where workspace_id = %s and id = %s and user_id = %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, conversation_id, user_id))
                row = await cur.fetchone()
        if row is None:
            return None
        return ConversationRow.from_row(row)

    async def list_conversations(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        limit: int,
    ) -> list[ConversationSummaryRow]:
        query = """
            select id, title, created_at, updated_at
            from conversations
            where workspace_id = %s and user_id = %s
            order by updated_at desc
            limit %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, user_id, limit))
                rows = await cur.fetchall()
        return [ConversationSummaryRow.from_row(row) for row in rows]

    async def list_conversation_messages(
        self,
        *,
        workspace_id: UUID,
        conversation_id: UUID,
        user_id: UUID,
    ) -> list[ConversationMessageRow]:
        query = """
            select m.id, m.role, m.content, m.model_profile, m.sources, m.token_usage, m.created_at
            from messages m
            join conversations c on c.id = m.conversation_id
            where c.workspace_id = %s and c.id = %s and c.user_id = %s
            order by m.created_at asc
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, conversation_id, user_id))
                rows = await cur.fetchall()
        return [ConversationMessageRow.from_row(row) for row in rows]
