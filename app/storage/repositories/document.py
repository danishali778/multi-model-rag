from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.domain.errors import NotFoundError
from app.storage.db.session import Database
from app.storage.models.document import (
    DocumentCreateInput,
    DocumentDetailRow,
    DocumentIngestionRow,
    DocumentListRow,
    DocumentMetadataUpdateInput,
    DocumentSourceRow,
    DocumentStorageUpdateInput,
)
from app.storage.repositories._helpers import public_metadata


class DocumentRepository:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def create_document(self, payload: DocumentCreateInput, *, conn=None) -> UUID:
        query = """
            insert into documents (
                id, workspace_id, created_by, title, source_type, source_uri, storage_bucket,
                storage_path, content_hash, status, sensitivity, metadata
            )
            values (
                coalesce(%(id)s, gen_random_uuid()), %(workspace_id)s, %(created_by)s, %(title)s, %(source_type)s, %(source_uri)s,
                %(storage_bucket)s, %(storage_path)s, %(content_hash)s, %(status)s,
                %(sensitivity)s, %(metadata)s::jsonb
            )
            returning id
        """
        db_payload = payload.model_dump()
        db_payload["metadata"] = json.dumps(db_payload["metadata"])
        if conn is None:
            async with self.db.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, db_payload)
                    row = await cur.fetchone()
                    await conn.commit()
        else:
            async with conn.cursor() as cur:
                await cur.execute(query, db_payload)
                row = await cur.fetchone()
        return row["id"]

    async def list_documents(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        status: str | None,
        source_type: str | None,
        limit: int,
    ) -> list[DocumentListRow]:
        filters = ["d.workspace_id = %s", "d.created_by = %s", "d.deleted_at is null"]
        params: list[Any] = [workspace_id, user_id]
        if status:
            filters.append("d.status = %s")
            params.append(status)
        if source_type:
            filters.append("d.source_type = %s")
            params.append(source_type)
        query = f"""
            select d.id, d.title, d.source_type, d.status, d.sensitivity, d.created_at, d.updated_at
            from documents d
            where {' and '.join(filters)}
            order by d.created_at desc
            limit %s
        """
        params.append(limit)
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall()
        return [DocumentListRow.from_row(row) for row in rows]

    async def get_document(self, *, workspace_id: UUID, document_id: UUID, user_id: UUID) -> DocumentDetailRow:
        query = """
            select d.id, d.title, d.source_type, d.status, d.metadata,
                   count(dc.id) filter (where dc.chunk_role = 'child')::int as chunk_count
            from documents d
            left join document_chunks dc on dc.document_id = d.id
            where d.workspace_id = %s and d.id = %s and d.created_by = %s and d.deleted_at is null
            group by d.id
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, document_id, user_id))
                row = await cur.fetchone()
        if not row:
            raise NotFoundError("Document not found.")
        row["metadata"] = public_metadata(row["metadata"])
        return DocumentDetailRow.from_row(row)

    async def get_document_source(self, *, workspace_id: UUID, document_id: UUID, user_id: UUID) -> DocumentSourceRow:
        query = """
            select d.id, d.title, d.source_type, d.sensitivity, d.metadata
            from documents d
            where d.workspace_id = %s and d.id = %s and d.created_by = %s and d.deleted_at is null
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, document_id, user_id))
                row = await cur.fetchone()
        if not row:
            raise NotFoundError("Document not found.")
        return DocumentSourceRow.from_row(row)

    async def get_document_for_ingestion(self, *, workspace_id: UUID, document_id: UUID) -> DocumentIngestionRow:
        query = """
            select id, workspace_id, title, source_type, source_uri, storage_bucket, storage_path,
                   content_hash, status, sensitivity, metadata
            from documents
            where workspace_id = %s and id = %s and deleted_at is null
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, document_id))
                row = await cur.fetchone()
        if not row:
            raise NotFoundError("Document not found.")
        return DocumentIngestionRow.from_row(row)

    async def update_document_storage(self, payload: DocumentStorageUpdateInput, *, conn=None) -> None:
        query = """
            update documents
            set source_uri = %s,
                storage_bucket = %s,
                storage_path = %s,
                updated_at = now()
            where id = %s
        """
        if conn is None:
            async with self.db.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        query,
                        (payload.source_uri, payload.storage_bucket, payload.storage_path, payload.document_id),
                    )
                    await conn.commit()
            return
        async with conn.cursor() as cur:
            await cur.execute(
                query,
                (payload.source_uri, payload.storage_bucket, payload.storage_path, payload.document_id),
            )

    async def update_document_ingestion_metadata(self, payload: DocumentMetadataUpdateInput) -> None:
        query = """
            update documents
            set metadata = coalesce(metadata, '{}'::jsonb) || %s::jsonb,
                status = coalesce(%s, status),
                updated_at = now()
            where id = %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (json.dumps(payload.metadata_updates), payload.status, payload.document_id),
                )
                await conn.commit()

    async def update_document_status(self, document_id: UUID, status: str, *, content_hash: str | None) -> None:
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    update documents
                    set status = %s, content_hash = coalesce(%s, content_hash), updated_at = now()
                    where id = %s
                    """,
                    (status, content_hash, document_id),
                )
                await conn.commit()
