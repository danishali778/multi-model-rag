from __future__ import annotations

import json
from uuid import UUID

from app.core.config import Settings
from app.domain.errors import NotFoundError
from app.storage.db.session import Database
from app.storage.models.ingestion import (
    ChunkReplacementInput,
    IngestionJobCreateInput,
    IngestionJobRow,
    IngestionJobUpdateInput,
    StageExtractedDocumentInput,
    UserIngestionJobRow,
)
from app.storage.repositories._helpers import vector_literal


class IngestionRepository:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def create_ingestion_job(self, payload: IngestionJobCreateInput, *, conn=None) -> UUID:
        query = """
            insert into ingestion_jobs (id, workspace_id, document_id, status, stage, attempts, stats)
            values (coalesce(%s, gen_random_uuid()), %s, %s, 'queued', 'queued', 1, '{}'::jsonb)
            returning id
        """
        if conn is None:
            async with self.db.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, (payload.id, payload.workspace_id, payload.document_id))
                    row = await cur.fetchone()
                    await conn.commit()
        else:
            async with conn.cursor() as cur:
                await cur.execute(query, (payload.id, payload.workspace_id, payload.document_id))
                row = await cur.fetchone()
        return row["id"]

    async def update_job(self, job_id: UUID, payload: IngestionJobUpdateInput) -> None:
        query = """
            update ingestion_jobs
            set status = %s, stage = %s,
                attempts = coalesce(%s, attempts),
                error_code = %s,
                error_message = %s,
                stats = coalesce(stats, '{}'::jsonb) || %s::jsonb,
                started_at = case when started_at is null then now() else started_at end,
                finished_at = case when %s in ('succeeded', 'failed', 'cancelled') then now() else finished_at end
            where id = %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        payload.status,
                        payload.stage,
                        payload.attempts,
                        payload.error_code,
                        payload.error_message,
                        json.dumps(payload.stats),
                        payload.status,
                        job_id,
                    ),
                )
                await conn.commit()

    async def get_ingestion_job(self, *, workspace_id: UUID, job_id: UUID, user_id: UUID) -> IngestionJobRow:
        query = """
            select ij.*
            from ingestion_jobs ij
            join documents d on d.id = ij.document_id
            where ij.workspace_id = %s and ij.id = %s and d.created_by = %s and d.deleted_at is null
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, job_id, user_id))
                row = await cur.fetchone()
        if not row:
            raise NotFoundError("Ingestion job not found.")
        return IngestionJobRow.from_row(row)

    async def get_ingestion_job_internal(self, *, workspace_id: UUID, job_id: UUID) -> IngestionJobRow:
        query = """
            select *
            from ingestion_jobs
            where workspace_id = %s and id = %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, job_id))
                row = await cur.fetchone()
        if not row:
            raise NotFoundError("Ingestion job not found.")
        return IngestionJobRow.from_row(row)

    async def stage_extracted_document(self, payload: StageExtractedDocumentInput) -> None:
        updates = {
            "_staged_text": payload.extracted_text,
            "_processed_storage_bucket": payload.processed_storage_bucket,
            "_processed_storage_path": payload.processed_storage_path,
            "_parser_version": payload.parser_version,
            "_skip_indexing": payload.should_skip,
            "_chunking_version": payload.chunking_version,
            "_embedding_model": payload.embedding_model,
            **payload.metadata,
        }
        query = """
            update documents
            set metadata = coalesce(metadata, '{}'::jsonb) || %s::jsonb,
                content_hash = %s,
                status = 'processing',
                updated_at = now()
            where id = %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (json.dumps(updates), payload.content_hash, payload.document_id))
                await conn.commit()

    async def replace_document_chunks(self, payload: ChunkReplacementInput) -> None:
        if len(payload.chunks) != len(payload.embeddings):
            raise ValueError("Chunk and embedding counts must match.")
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("delete from document_structure_edges where document_id = %s", (payload.document_id,))
                await cur.execute("delete from document_chunks where document_id = %s", (payload.document_id,))
                await cur.execute("delete from document_structure_nodes where document_id = %s", (payload.document_id,))
                await cur.execute("delete from document_blocks where document_id = %s", (payload.document_id,))
                for block in payload.blocks:
                    await cur.execute(
                        """
                        insert into document_blocks (
                            id, workspace_id, document_id, block_type, text, page_number,
                            heading_level, section_path, order_index, parent_block_id, metadata
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb)
                        """,
                        (
                            block.id,
                            payload.workspace_id,
                            payload.document_id,
                            block.block_type,
                            block.text,
                            block.page_number,
                            block.heading_level,
                            json.dumps(block.section_path),
                            block.order_index,
                            block.parent_block_id,
                            json.dumps(block.metadata),
                        ),
                    )
                for node in payload.nodes:
                    await cur.execute(
                        """
                        insert into document_structure_nodes (
                            id, workspace_id, document_id, node_type, node_key, title,
                            section_path, level, page_start, page_end, block_order_start,
                            block_order_end, parent_node_id, metadata
                        )
                        values (
                            %s, %s, %s, %s, %s, %s,
                            %s::jsonb, %s, %s, %s, %s,
                            %s, %s, %s::jsonb
                        )
                        """,
                        (
                            node.id,
                            payload.workspace_id,
                            payload.document_id,
                            node.node_type,
                            node.node_key,
                            node.title,
                            json.dumps(node.section_path),
                            node.level,
                            node.page_start,
                            node.page_end,
                            node.block_order_start,
                            node.block_order_end,
                            node.parent_node_id,
                            json.dumps(node.metadata),
                        ),
                    )
                for edge in payload.edges:
                    await cur.execute(
                        """
                        insert into document_structure_edges (
                            id, workspace_id, document_id, from_node_id, to_node_id,
                            edge_type, edge_order, metadata
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            edge.id,
                            payload.workspace_id,
                            payload.document_id,
                            edge.from_node_id,
                            edge.to_node_id,
                            edge.edge_type,
                            edge.edge_order,
                            json.dumps(edge.metadata),
                        ),
                    )
                for chunk, embedding in zip(payload.chunks, payload.embeddings, strict=True):
                    await cur.execute(
                        """
                        insert into document_chunks (
                            id, workspace_id, document_id, chunk_index, content, content_hash,
                            token_count, metadata, embedding, embedding_model, chunking_version,
                            parent_block_id, chunk_role, page_number, chunk_type, section_title,
                            subsection_title, section_path, block_order_start, block_order_end,
                            node_id, parent_node_id, previous_chunk_id, next_chunk_id, level,
                            page_start, page_end, embedding_text
                        )
                        values (
                            %s, %s, %s, %s, %s, md5(%s), %s, %s::jsonb, %s::extensions.vector, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            chunk.id,
                            payload.workspace_id,
                            payload.document_id,
                            chunk.chunk_index,
                            chunk.content,
                            chunk.content,
                            chunk.token_count,
                            json.dumps(chunk.metadata),
                            vector_literal(embedding),
                            payload.embedding_model,
                            payload.chunking_version,
                            chunk.parent_block_id,
                            chunk.chunk_role,
                            chunk.page_number,
                            chunk.chunk_type,
                            chunk.section_title,
                            chunk.subsection_title,
                            json.dumps(chunk.section_path or []),
                            chunk.block_order_start,
                            chunk.block_order_end,
                            chunk.node_id,
                            chunk.parent_node_id,
                            None,
                            None,
                            chunk.level,
                            chunk.page_start,
                            chunk.page_end,
                            chunk.embedding_text,
                        ),
                    )
                for chunk in payload.chunks:
                    await cur.execute(
                        """
                        update document_chunks
                        set previous_chunk_id = %s,
                            next_chunk_id = %s
                        where id = %s
                        """,
                        (
                            chunk.previous_chunk_id,
                            chunk.next_chunk_id,
                            chunk.id,
                        ),
                    )
                await conn.commit()

    async def list_user_ingestion_jobs(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        limit: int,
    ) -> list[UserIngestionJobRow]:
        query = """
            select ij.id, ij.document_id, ij.status, ij.stage, ij.attempts, ij.error_code, ij.error_message,
                   ij.stats, ij.created_at, ij.finished_at
            from ingestion_jobs ij
            join documents d on d.id = ij.document_id
            where ij.workspace_id = %s and d.created_by = %s and d.deleted_at is null
            order by ij.created_at desc
            limit %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, user_id, limit))
                rows = await cur.fetchall()
        return [UserIngestionJobRow.from_row(row) for row in rows]
