from __future__ import annotations

import json
from uuid import UUID

from app.core.config import Settings
from app.domain.errors import NotFoundError
from app.storage.db.session import Database
from app.storage.models.voice import VoiceTurnCreateInput, VoiceTurnRow, VoiceTurnUpdateInput


class VoiceRepository:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def create_voice_turn(self, payload: VoiceTurnCreateInput) -> UUID:
        query = """
            insert into voice_turns (
                workspace_id, conversation_id, user_message_id, assistant_message_id,
                input_audio_bucket, input_audio_path, output_audio_bucket, output_audio_path,
                transcript, transcript_confidence, input_duration_ms, output_duration_ms,
                stt_provider, stt_model, tts_provider, tts_model, metadata
            )
            values (
                %(workspace_id)s, %(conversation_id)s, %(user_message_id)s, %(assistant_message_id)s,
                %(input_audio_bucket)s, %(input_audio_path)s, %(output_audio_bucket)s, %(output_audio_path)s,
                %(transcript)s, %(transcript_confidence)s, %(input_duration_ms)s, %(output_duration_ms)s,
                %(stt_provider)s, %(stt_model)s, %(tts_provider)s, %(tts_model)s, %(metadata)s::jsonb
            )
            returning id
        """
        values = payload.model_dump()
        values["metadata"] = json.dumps(values["metadata"])
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, values)
                row = await cur.fetchone()
                await conn.commit()
        return row["id"]

    async def attach_input_audio(self, voice_turn_id: UUID, payload: VoiceTurnUpdateInput) -> None:
        await self._update_audio_fields(voice_turn_id, payload)

    async def attach_output_audio(self, voice_turn_id: UUID, payload: VoiceTurnUpdateInput) -> None:
        await self._update_audio_fields(voice_turn_id, payload)

    async def _update_audio_fields(self, voice_turn_id: UUID, payload: VoiceTurnUpdateInput) -> None:
        query = """
            update voice_turns
            set input_audio_bucket = coalesce(%s, input_audio_bucket),
                input_audio_path = coalesce(%s, input_audio_path),
                output_audio_bucket = coalesce(%s, output_audio_bucket),
                output_audio_path = coalesce(%s, output_audio_path),
                output_duration_ms = coalesce(%s, output_duration_ms),
                metadata = coalesce(metadata, '{}'::jsonb) || %s::jsonb,
                updated_at = timezone('utc', now())
            where id = %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        payload.input_audio_bucket,
                        payload.input_audio_path,
                        payload.output_audio_bucket,
                        payload.output_audio_path,
                        payload.output_duration_ms,
                        json.dumps(payload.metadata),
                        voice_turn_id,
                    ),
                )
                await conn.commit()

    async def get_voice_turn(self, *, workspace_id: UUID, voice_turn_id: UUID) -> VoiceTurnRow:
        query = """
            select *
            from voice_turns
            where workspace_id = %s and id = %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, voice_turn_id))
                row = await cur.fetchone()
        if not row:
            raise NotFoundError("Voice turn not found.")
        return VoiceTurnRow.from_row(row)

    async def list_voice_turns_for_conversation(self, *, workspace_id: UUID, conversation_id: UUID) -> list[VoiceTurnRow]:
        query = """
            select *
            from voice_turns
            where workspace_id = %s and conversation_id = %s
            order by created_at asc
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, conversation_id))
                rows = await cur.fetchall()
        return [VoiceTurnRow.from_row(row) for row in rows]
