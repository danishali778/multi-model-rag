from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.storage.db.session import Database
from app.storage.models.retrieval import ParentContextRow, RetrievalCandidateRow
from app.storage.repositories._helpers import sensitivity_clause, vector_literal


class RetrievalRepository:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def search_chunks(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        query_embedding: list[float],
        top_k: int,
        filters: dict[str, Any],
    ) -> list[RetrievalCandidateRow]:
        clauses = ["dc.workspace_id = %s", "d.deleted_at is null", "dc.chunk_role = 'child'"]
        params: list[Any] = [vector_literal(query_embedding), workspace_id]
        metadata_filters, document_ids = _split_filters(filters)
        if document_ids:
            clauses.append("dc.document_id = any(%s)")
            params.append(document_ids)
        if metadata_filters:
            clauses.append("dc.metadata @> %s::jsonb")
            params.append(json.dumps(metadata_filters))
        params.extend([vector_literal(query_embedding), top_k])
        query = f"""
            select
                dc.id,
                dc.document_id,
                dc.chunk_index,
                dc.content,
                dc.metadata,
                d.title,
                d.sensitivity,
                dc.parent_block_id,
                dc.page_number,
                dc.chunk_type,
                dc.section_title,
                dc.subsection_title,
                dc.section_path,
                1 - (dc.embedding <=> %s::extensions.vector) as vector_score
            from document_chunks dc
            join documents d on d.id = dc.document_id
            where {' and '.join(clauses)}
            order by dc.embedding <=> %s::extensions.vector
            limit %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall()
        return [RetrievalCandidateRow.from_row(row) for row in rows]

    async def search_vector_candidates(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        query_embedding: list[float],
        limit: int,
        filters: dict[str, Any],
        sensitivity_ceiling: str | None,
    ) -> list[RetrievalCandidateRow]:
        clauses = ["dc.workspace_id = %s", "d.deleted_at is null", "dc.chunk_role = 'child'"]
        params: list[Any] = [workspace_id]
        metadata_filters, document_ids = _split_filters(filters)
        if document_ids:
            clauses.append("dc.document_id = any(%s)")
            params.append(document_ids)
        if metadata_filters:
            clauses.append("dc.metadata @> %s::jsonb")
            params.append(json.dumps(metadata_filters))
        if sensitivity_ceiling:
            clauses.append(sensitivity_clause("d"))
            params.append(sensitivity_ceiling)
        params.extend([vector_literal(query_embedding), limit])
        query = f"""
            select
                dc.id,
                dc.document_id,
                dc.chunk_index,
                dc.content,
                dc.metadata,
                d.title,
                d.sensitivity,
                dc.parent_block_id,
                dc.page_number,
                dc.chunk_type,
                dc.section_title,
                dc.subsection_title,
                dc.section_path,
                1 - (dc.embedding <=> %s::extensions.vector) as vector_score
            from document_chunks dc
            join documents d on d.id = dc.document_id
            where {' and '.join(clauses)}
            order by dc.embedding <=> %s::extensions.vector
            limit %s
        """
        vector_param = vector_literal(query_embedding)
        execution_params = [vector_param, *params[:-2], vector_param, params[-1]]
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, execution_params)
                rows = await cur.fetchall()
        return [RetrievalCandidateRow.from_row(row) for row in rows]

    async def search_fts_candidates(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        query_text: str,
        limit: int,
        filters: dict[str, Any],
        sensitivity_ceiling: str | None,
    ) -> list[RetrievalCandidateRow]:
        clauses = [
            "dc.workspace_id = %s",
            "d.deleted_at is null",
            "dc.chunk_role = 'child'",
            "dc.search_vector @@ websearch_to_tsquery('english', %s)",
        ]
        params: list[Any] = [workspace_id]
        metadata_filters, document_ids = _split_filters(filters)
        if document_ids:
            clauses.append("dc.document_id = any(%s)")
            params.append(document_ids)
        if metadata_filters:
            clauses.append("dc.metadata @> %s::jsonb")
            params.append(json.dumps(metadata_filters))
        if sensitivity_ceiling:
            clauses.append(sensitivity_clause("d"))
            params.append(sensitivity_ceiling)
        params.append(limit)
        query = f"""
            select
                dc.id,
                dc.document_id,
                dc.chunk_index,
                dc.content,
                dc.metadata,
                d.title,
                d.sensitivity,
                dc.parent_block_id,
                dc.page_number,
                dc.chunk_type,
                dc.section_title,
                dc.subsection_title,
                dc.section_path,
                ts_rank_cd(dc.search_vector, websearch_to_tsquery('english', %s)) as fts_score
            from document_chunks dc
            join documents d on d.id = dc.document_id
            where {' and '.join(clauses)}
            order by fts_score desc, dc.chunk_index asc
            limit %s
        """
        execution_params = [query_text, workspace_id, query_text, *params[1:]]
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, execution_params)
                rows = await cur.fetchall()
        return [RetrievalCandidateRow.from_row(row) for row in rows]

    async def get_parent_context_chunks(self, parent_block_ids: list[UUID]) -> dict[UUID, ParentContextRow]:
        if not parent_block_ids:
            return {}
        query = """
            select parent_block_id, content, page_number, chunk_type, section_title, subsection_title, section_path
            from document_chunks
            where chunk_role = 'parent' and parent_block_id = any(%s)
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (parent_block_ids,))
                rows = await cur.fetchall()
        return {
            row["parent_block_id"]: ParentContextRow.from_row(row)
            for row in rows
        }

    async def diagnose_empty_retrieval(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        query_text: str,
        filters: dict[str, Any],
        sensitivity_ceiling: str | None,
    ) -> str:
        filters_sql = ["dc.workspace_id = %s", "d.deleted_at is null", "dc.chunk_role = 'child'"]
        params: list[Any] = [workspace_id]
        if query_text:
            filters_sql.append("dc.search_vector @@ websearch_to_tsquery('english', %s)")
            params.append(query_text)
        metadata_filters, document_ids = _split_filters(filters)
        if document_ids:
            filters_sql.append("dc.document_id = any(%s)")
            params.append(document_ids)
        if metadata_filters:
            filters_sql.append("dc.metadata @> %s::jsonb")
            params.append(json.dumps(metadata_filters))
        if sensitivity_ceiling:
            filters_sql.append(sensitivity_clause("d"))
            params.append(sensitivity_ceiling)
        query = f"""
            select exists(
                select 1
                from document_chunks dc
                join documents d on d.id = dc.document_id
                where {' and '.join(filters_sql)}
            ) as matched
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                row = await cur.fetchone()
        return "no_match" if row and not bool(row["matched"]) else "matched"


def _split_filters(filters: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if not filters:
        return {}, []
    filter_copy = dict(filters)
    document_ids = filter_copy.pop("document_ids", [])
    return filter_copy, [str(item) for item in document_ids]
