from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.config import Settings
from app.storage.db.session import Database
from app.storage.models.idempotency import IdempotencyRequestRow

REPLAY_RETENTION_HOURS = 24
STALE_LOCK_MINUTES = 15


class IdempotencyRepository:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def claim_request(
        self,
        *,
        user_id: UUID,
        workspace_id: UUID | None,
        route_key: str,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[bool, IdempotencyRequestRow]:
        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=REPLAY_RETENTION_HOURS)
        stale_before = now - timedelta(minutes=STALE_LOCK_MINUTES)

        insert_query = """
            insert into idempotency_requests (
                user_id, workspace_id, route_key, idempotency_key, request_hash,
                status, locked_at, expires_at, updated_at
            )
            values (%s, %s, %s, %s, %s, 'in_progress', %s, %s, %s)
            on conflict (user_id, route_key, idempotency_key) do nothing
            returning *
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    insert_query,
                    (user_id, workspace_id, route_key, idempotency_key, request_hash, now, expires_at, now),
                )
                inserted = await cur.fetchone()
                if inserted:
                    await conn.commit()
                    return True, IdempotencyRequestRow.from_row(inserted)

                await cur.execute(
                    """
                    select *
                    from idempotency_requests
                    where user_id = %s and route_key = %s and idempotency_key = %s
                    """,
                    (user_id, route_key, idempotency_key),
                )
                existing = await cur.fetchone()
                if existing is None:
                    await conn.rollback()
                    raise RuntimeError("Idempotency request row was not found after insert conflict.")
                row = IdempotencyRequestRow.from_row(existing)

                reclaimed = await self._try_reclaim(
                    cur=cur,
                    row=row,
                    workspace_id=workspace_id,
                    request_hash=request_hash,
                    now=now,
                    stale_before=stale_before,
                    expires_at=expires_at,
                )
                if reclaimed is not None:
                    await conn.commit()
                    return True, reclaimed
                await conn.commit()
                return False, row

    async def complete_request(
        self,
        *,
        request_id: UUID,
        response_status_code: int,
        response_body: dict,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
    ) -> None:
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    update idempotency_requests
                    set status = 'completed',
                        response_status_code = %s,
                        response_body = %s::jsonb,
                        resource_type = coalesce(%s, resource_type),
                        resource_id = coalesce(%s, resource_id),
                        completed_at = now(),
                        expires_at = now() + interval '24 hours',
                        updated_at = now()
                    where id = %s
                    """,
                    (response_status_code, json.dumps(response_body), resource_type, resource_id, request_id),
                )
                await conn.commit()

    async def fail_request(self, *, request_id: UUID) -> None:
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    update idempotency_requests
                    set status = 'failed',
                        updated_at = now()
                    where id = %s
                    """,
                    (request_id,),
                )
                await conn.commit()

    async def _try_reclaim(
        self,
        *,
        cur,
        row: IdempotencyRequestRow,
        workspace_id: UUID | None,
        request_hash: str,
        now: datetime,
        stale_before: datetime,
        expires_at: datetime,
    ) -> IdempotencyRequestRow | None:
        should_reclaim = False
        if row.status == "failed" and row.request_hash == request_hash:
            should_reclaim = True
        elif row.status == "in_progress" and row.request_hash == request_hash and row.locked_at <= stale_before:
            should_reclaim = True
        elif row.expires_at is not None and row.expires_at <= now:
            should_reclaim = True

        if not should_reclaim:
            return None

        await cur.execute(
            """
            update idempotency_requests
            set workspace_id = %s,
                request_hash = %s,
                status = 'in_progress',
                response_status_code = null,
                response_body = null,
                resource_type = resource_type,
                resource_id = resource_id,
                locked_at = %s,
                completed_at = null,
                expires_at = %s,
                updated_at = %s
            where id = %s
              and (
                (status = 'failed' and request_hash = %s)
                or (status = 'in_progress' and request_hash = %s and locked_at <= %s)
                or (expires_at is not null and expires_at <= %s)
              )
            returning *
            """,
            (
                workspace_id,
                request_hash,
                now,
                expires_at,
                now,
                row.id,
                request_hash,
                request_hash,
                stale_before,
                now,
            ),
        )
        updated = await cur.fetchone()
        if updated is None:
            return None
        return IdempotencyRequestRow.from_row(updated)
