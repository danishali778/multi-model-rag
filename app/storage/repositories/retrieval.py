from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.storage.db.session import Database
from app.storage.models.retrieval import ParentContextRow, RetrievalCandidateRow, StructureNodeRow
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
                {_chunk_select_fields("dc", "d")},
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
                {_chunk_select_fields("dc", "d")},
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
                {_chunk_select_fields("dc", "d")},
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
            select parent_block_id, content, page_number, chunk_type, section_title, subsection_title,
                   section_path, node_id, parent_node_id, level, page_start, page_end
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

    async def get_chunks_by_ids(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        chunk_ids: list[UUID],
        sensitivity_ceiling: str | None,
    ) -> dict[UUID, RetrievalCandidateRow]:
        if not chunk_ids:
            return {}
        clauses = ["dc.workspace_id = %s", "dc.id = any(%s)", "d.deleted_at is null"]
        params: list[Any] = [workspace_id, chunk_ids]
        if sensitivity_ceiling:
            clauses.append(sensitivity_clause("d"))
            params.append(sensitivity_ceiling)
        query = f"""
            select {_chunk_select_fields("dc", "d")}
            from document_chunks dc
            join documents d on d.id = dc.document_id
            where {' and '.join(clauses)}
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall()
        return {row["id"]: RetrievalCandidateRow.from_row(row) for row in rows}

    async def get_chunks_by_node_ids(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        node_ids: list[UUID],
        chunk_role: str | None,
        sensitivity_ceiling: str | None,
    ) -> list[RetrievalCandidateRow]:
        if not node_ids:
            return []
        clauses = ["dc.workspace_id = %s", "dc.node_id = any(%s)", "d.deleted_at is null"]
        params: list[Any] = [workspace_id, node_ids]
        if chunk_role:
            clauses.append("dc.chunk_role = %s")
            params.append(chunk_role)
        if sensitivity_ceiling:
            clauses.append(sensitivity_clause("d"))
            params.append(sensitivity_ceiling)
        query = f"""
            select {_chunk_select_fields("dc", "d")}
            from document_chunks dc
            join documents d on d.id = dc.document_id
            where {' and '.join(clauses)}
            order by dc.block_order_start asc, dc.chunk_index asc
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall()
        return [RetrievalCandidateRow.from_row(row) for row in rows]

    async def get_neighboring_chunks(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        chunk_ids: list[UUID],
        sensitivity_ceiling: str | None,
    ) -> list[RetrievalCandidateRow]:
        if not chunk_ids:
            return []
        clauses = ["dc.workspace_id = %s", "d.deleted_at is null"]
        params: list[Any] = [workspace_id]
        if sensitivity_ceiling:
            clauses.append(sensitivity_clause("d"))
            params.append(sensitivity_ceiling)
        query = f"""
            with seed as (
                select previous_chunk_id as neighbor_id
                from document_chunks
                where workspace_id = %s and id = any(%s)
                union
                select next_chunk_id as neighbor_id
                from document_chunks
                where workspace_id = %s and id = any(%s)
            )
            select {_chunk_select_fields("dc", "d")}
            from document_chunks dc
            join documents d on d.id = dc.document_id
            where {' and '.join(clauses)}
              and dc.chunk_role = 'child'
              and dc.id in (select neighbor_id from seed where neighbor_id is not null)
            order by dc.block_order_start asc, dc.chunk_index asc
        """
        execution_params = [workspace_id, chunk_ids, workspace_id, chunk_ids, *params]
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, execution_params)
                rows = await cur.fetchall()
        return [RetrievalCandidateRow.from_row(row) for row in rows]

    async def get_nodes_by_ids(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        node_ids: list[UUID],
    ) -> dict[UUID, StructureNodeRow]:
        if not node_ids:
            return {}
        query = """
            select id, document_id, node_type, node_key, title, section_path, level,
                   page_start, page_end, block_order_start, block_order_end,
                   parent_node_id, metadata
            from document_structure_nodes
            where workspace_id = %s and id = any(%s)
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, node_ids))
                rows = await cur.fetchall()
        return {row["id"]: StructureNodeRow.from_row(row) for row in rows}

    async def get_ancestor_nodes(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        node_ids: list[UUID],
        max_depth: int = 2,
    ) -> list[StructureNodeRow]:
        if not node_ids:
            return []
        query = """
            with recursive ancestors as (
                select id, document_id, node_type, node_key, title, section_path, level,
                       page_start, page_end, block_order_start, block_order_end,
                       parent_node_id, metadata, 0 as depth
                from document_structure_nodes
                where workspace_id = %s and id = any(%s)
                union all
                select parent.id, parent.document_id, parent.node_type, parent.node_key, parent.title, parent.section_path,
                       parent.level, parent.page_start, parent.page_end, parent.block_order_start, parent.block_order_end,
                       parent.parent_node_id, parent.metadata, child.depth + 1
                from document_structure_nodes parent
                join ancestors child on parent.id = child.parent_node_id
                where parent.workspace_id = %s and child.depth < %s
            )
            select distinct id, document_id, node_type, node_key, title, section_path, level,
                            page_start, page_end, block_order_start, block_order_end,
                            parent_node_id, metadata
            from ancestors
            where depth > 0
            order by block_order_start asc
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, node_ids, workspace_id, max_depth))
                rows = await cur.fetchall()
        return [StructureNodeRow.from_row(row) for row in rows]

    async def get_sibling_nodes(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        node_ids: list[UUID],
    ) -> list[StructureNodeRow]:
        if not node_ids:
            return []
        query = """
            with seed as (
                select id, parent_node_id, block_order_start
                from document_structure_nodes
                where workspace_id = %s and id = any(%s)
            )
            select distinct sibling.id, sibling.document_id, sibling.node_type, sibling.node_key, sibling.title,
                            sibling.section_path, sibling.level, sibling.page_start, sibling.page_end,
                            sibling.block_order_start, sibling.block_order_end, sibling.parent_node_id, sibling.metadata
            from document_structure_nodes sibling
            join seed on sibling.parent_node_id = seed.parent_node_id
            where sibling.workspace_id = %s and sibling.id <> seed.id
            order by sibling.block_order_start asc
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, node_ids, workspace_id))
                rows = await cur.fetchall()
        return [StructureNodeRow.from_row(row) for row in rows]

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


def _chunk_select_fields(chunk_alias: str, document_alias: str) -> str:
    return f"""
        {chunk_alias}.id,
        {chunk_alias}.document_id,
        {chunk_alias}.chunk_index,
        {chunk_alias}.content,
        {chunk_alias}.metadata,
        {document_alias}.title,
        {document_alias}.sensitivity,
        {chunk_alias}.parent_block_id,
        {chunk_alias}.page_number,
        {chunk_alias}.chunk_type,
        {chunk_alias}.section_title,
        {chunk_alias}.subsection_title,
        {chunk_alias}.section_path,
        {chunk_alias}.node_id,
        {chunk_alias}.parent_node_id,
        {chunk_alias}.previous_chunk_id,
        {chunk_alias}.next_chunk_id,
        {chunk_alias}.level,
        {chunk_alias}.page_start,
        {chunk_alias}.page_end,
        {chunk_alias}.chunking_version
    """
