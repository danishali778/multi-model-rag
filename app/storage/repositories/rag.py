from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.domain.entities.rag import (
    AuditLogRecord,
    ConversationMessage,
    ConversationSummary,
    EvaluationRunSummary,
    FeedbackRecord,
    RetrievalMetricsSummary,
    UsageBucket,
    UsageSummary,
)
from app.domain.errors import NotFoundError
from app.ingestion.chunking import ChunkDraft
from app.security.pii import redact_payload
from app.storage.db.session import Database


class RagRepository:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def list_tenants_for_user(self, user_id: UUID) -> list[dict[str, Any]]:
        query = """
            select t.id, t.name, t.slug, tm.role
            from tenant_members tm
            join tenants t on t.id = tm.tenant_id
            where tm.user_id = %s and tm.status = 'active' and t.status = 'active'
            order by t.name
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (user_id,))
                return await cur.fetchall()

    async def user_has_tenant_access(self, user_id: UUID, tenant_id: UUID) -> bool:
        query = """
            select exists(
                select 1 from tenant_members
                where tenant_id = %s and user_id = %s and status = 'active'
            ) as allowed
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id, user_id))
                row = await cur.fetchone()
                return bool(row["allowed"])

    async def get_tenant_role(self, user_id: UUID, tenant_id: UUID) -> str | None:
        query = """
            select role
            from tenant_members
            where tenant_id = %s and user_id = %s and status = 'active'
            limit 1
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id, user_id))
                row = await cur.fetchone()
        return row["role"] if row else None

    async def create_document(self, **payload: Any) -> UUID:
        query = """
            insert into documents (
                tenant_id, created_by, title, source_type, source_uri, storage_bucket,
                storage_path, content_hash, status, sensitivity, metadata
            )
            values (
                %(tenant_id)s, %(created_by)s, %(title)s, %(source_type)s, %(source_uri)s,
                %(storage_bucket)s, %(storage_path)s, %(content_hash)s, %(status)s,
                %(sensitivity)s, %(metadata)s::jsonb
            )
            returning id
        """
        payload["metadata"] = json.dumps(payload["metadata"])
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, payload)
                row = await cur.fetchone()
                await conn.commit()
                return row["id"]

    async def set_document_acl_groups(self, *, tenant_id: UUID, document_id: UUID, group_ids: list[UUID]) -> None:
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("delete from document_acl_groups where document_id = %s", (document_id,))
                for group_id in group_ids:
                    await cur.execute(
                        """
                        insert into document_acl_groups (tenant_id, document_id, group_id, access_level)
                        values (%s, %s, %s, 'read')
                        """,
                        (tenant_id, document_id, group_id),
                    )
                await conn.commit()

    async def create_ingestion_job(self, *, tenant_id: UUID, document_id: UUID) -> UUID:
        query = """
            insert into ingestion_jobs (tenant_id, document_id, status, stage, attempts, stats)
            values (%s, %s, 'queued', 'queued', 1, '{}'::jsonb)
            returning id
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id, document_id))
                row = await cur.fetchone()
                await conn.commit()
                return row["id"]

    async def update_job(
        self,
        job_id: UUID,
        *,
        status: str,
        stage: str,
        error_code: str | None = None,
        error_message: str | None = None,
        stats: dict[str, Any] | None = None,
        attempts: int | None = None,
    ) -> None:
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
                        status,
                        stage,
                        attempts,
                        error_code,
                        error_message,
                        json.dumps(stats or {}),
                        status,
                        job_id,
                    ),
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

    async def replace_document_chunks(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        chunks: list[ChunkDraft],
        embeddings: list[list[float]],
        embedding_model: str,
        chunking_version: str,
    ) -> None:
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("delete from document_chunks where document_id = %s", (document_id,))
                for chunk, embedding in zip(chunks, embeddings, strict=True):
                    await cur.execute(
                        """
                        insert into document_chunks (
                            tenant_id, document_id, chunk_index, content, content_hash,
                            token_count, metadata, embedding, embedding_model, chunking_version
                        )
                        values (%s, %s, %s, %s, md5(%s), %s, %s::jsonb, %s::extensions.vector, %s, %s)
                        """,
                        (
                            tenant_id,
                            document_id,
                            chunk.chunk_index,
                            chunk.content,
                            chunk.content,
                            chunk.token_count,
                            json.dumps(chunk.metadata),
                            _vector_literal(embedding),
                            embedding_model,
                            chunking_version,
                        ),
                    )
                await conn.commit()

    async def list_documents(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        status: str | None,
        source_type: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        filters = ["d.tenant_id = %s", "d.deleted_at is null", _document_access_clause()]
        params: list[Any] = [tenant_id, user_id]
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
                return await cur.fetchall()

    async def get_document(self, *, tenant_id: UUID, document_id: UUID, user_id: UUID) -> dict[str, Any]:
        query = f"""
            select d.id, d.title, d.source_type, d.status, d.metadata, count(dc.id)::int as chunk_count
            from documents d
            left join document_chunks dc on dc.document_id = d.id
            where d.tenant_id = %s and d.id = %s and d.deleted_at is null and {_document_access_clause(alias='d')}
            group by d.id
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id, document_id, user_id))
                row = await cur.fetchone()
        if not row:
            raise NotFoundError("Document not found.")
        row["metadata"] = _public_metadata(row["metadata"])
        return row

    async def get_document_source(self, *, tenant_id: UUID, document_id: UUID, user_id: UUID) -> dict[str, Any]:
        query = f"""
            select d.id, d.title, d.source_type, d.sensitivity, d.metadata
            from documents d
            where d.tenant_id = %s and d.id = %s and d.deleted_at is null and {_document_access_clause(alias='d')}
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id, document_id, user_id))
                row = await cur.fetchone()
        if not row:
            raise NotFoundError("Document not found.")
        return row

    async def get_ingestion_job(self, *, tenant_id: UUID, job_id: UUID, user_id: UUID) -> dict[str, Any]:
        query = f"""
            select ij.*
            from ingestion_jobs ij
            join documents d on d.id = ij.document_id
            where ij.tenant_id = %s and ij.id = %s and {_document_access_clause(alias='d')}
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id, job_id, user_id))
                row = await cur.fetchone()
        if not row:
            raise NotFoundError("Ingestion job not found.")
        return row

    async def get_ingestion_job_internal(self, *, tenant_id: UUID, job_id: UUID) -> dict[str, Any]:
        query = """
            select *
            from ingestion_jobs
            where tenant_id = %s and id = %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id, job_id))
                row = await cur.fetchone()
        if not row:
            raise NotFoundError("Ingestion job not found.")
        return row

    async def get_document_for_ingestion(self, *, tenant_id: UUID, document_id: UUID) -> dict[str, Any]:
        query = """
            select id, tenant_id, title, source_type, source_uri, storage_bucket, storage_path,
                   content_hash, status, sensitivity, metadata
            from documents
            where tenant_id = %s and id = %s and deleted_at is null
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id, document_id))
                row = await cur.fetchone()
        if not row:
            raise NotFoundError("Document not found.")
        return row

    async def update_document_storage(
        self,
        *,
        document_id: UUID,
        source_uri: str,
        storage_bucket: str,
        storage_path: str,
    ) -> None:
        query = """
            update documents
            set source_uri = %s,
                storage_bucket = %s,
                storage_path = %s,
                updated_at = now()
            where id = %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (source_uri, storage_bucket, storage_path, document_id))
                await conn.commit()

    async def update_document_ingestion_metadata(
        self,
        document_id: UUID,
        *,
        metadata_updates: dict[str, Any],
        status: str | None = None,
    ) -> None:
        query = """
            update documents
            set metadata = coalesce(metadata, '{}'::jsonb) || %s::jsonb,
                status = coalesce(%s, status),
                updated_at = now()
            where id = %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (json.dumps(metadata_updates), status, document_id))
                await conn.commit()

    async def stage_extracted_document(
        self,
        *,
        document_id: UUID,
        content_hash: str,
        extracted_text: str,
        metadata: dict[str, Any],
        parser_version: str,
        processed_storage_bucket: str,
        processed_storage_path: str,
        should_skip: bool,
        chunking_version: str,
        embedding_model: str,
    ) -> None:
        updates = {
            "_staged_text": extracted_text,
            "_processed_storage_bucket": processed_storage_bucket,
            "_processed_storage_path": processed_storage_path,
            "_parser_version": parser_version,
            "_skip_indexing": should_skip,
            "_chunking_version": chunking_version,
            "_embedding_model": embedding_model,
            **metadata,
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
                await cur.execute(query, (json.dumps(updates), content_hash, document_id))
                await conn.commit()

    async def upsert_connector_checkpoint(
        self,
        *,
        tenant_id: UUID,
        connector_type: str,
        source_key: str,
        cursor: dict[str, Any],
        status: str,
        error_message: str | None = None,
    ) -> None:
        query = """
            insert into connector_sync_states (tenant_id, connector_type, source_key, cursor, status, error_message, last_run_at)
            values (%s, %s, %s, %s::jsonb, %s, %s, now())
            on conflict (tenant_id, connector_type, source_key)
            do update set cursor = excluded.cursor, status = excluded.status, error_message = excluded.error_message, last_run_at = now()
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (tenant_id, connector_type, source_key, json.dumps(cursor), status, error_message),
                )
                await conn.commit()

    async def search_chunks(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        query_embedding: list[float],
        top_k: int,
        filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        clauses = [
            "dc.tenant_id = %s",
            "d.deleted_at is null",
            _document_access_clause(alias="d"),
        ]
        params: list[Any] = [_vector_literal(query_embedding), tenant_id, user_id]
        if filters:
            clauses.append("dc.metadata @> %s::jsonb")
            params.append(json.dumps(filters))
        params.extend([_vector_literal(query_embedding), top_k])
        query = f"""
            select
                dc.id,
                dc.document_id,
                dc.content,
                d.title,
                1 - (dc.embedding <=> %s::extensions.vector) as score
            from document_chunks dc
            join documents d on d.id = dc.document_id
            where {' and '.join(clauses)}
            order by dc.embedding <=> %s::extensions.vector
            limit %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                return await cur.fetchall()

    async def search_vector_candidates(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        query_embedding: list[float],
        limit: int,
        filters: dict[str, Any],
        sensitivity_ceiling: str | None,
    ) -> list[dict[str, Any]]:
        clauses = [
            "dc.tenant_id = %s",
            "d.deleted_at is null",
            _document_access_clause(alias="d"),
        ]
        params: list[Any] = [tenant_id, user_id]
        if filters:
            clauses.append("dc.metadata @> %s::jsonb")
            params.append(json.dumps(filters))
        if sensitivity_ceiling:
            clauses.append(_sensitivity_clause("d"))
            params.append(sensitivity_ceiling)
        params.extend([_vector_literal(query_embedding), limit])
        query = f"""
            select
                dc.id,
                dc.document_id,
                dc.chunk_index,
                dc.content,
                dc.metadata,
                d.title,
                d.sensitivity,
                1 - (dc.embedding <=> %s::extensions.vector) as vector_score
            from document_chunks dc
            join documents d on d.id = dc.document_id
            where {' and '.join(clauses)}
            order by dc.embedding <=> %s::extensions.vector
            limit %s
        """
        vector_param = _vector_literal(query_embedding)
        execution_params = [vector_param, *params[:-2], vector_param, params[-1]]
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, execution_params)
                return await cur.fetchall()

    async def search_fts_candidates(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        query_text: str,
        limit: int,
        filters: dict[str, Any],
        sensitivity_ceiling: str | None,
    ) -> list[dict[str, Any]]:
        clauses = [
            "dc.tenant_id = %s",
            "d.deleted_at is null",
            _document_access_clause(alias='d'),
            "dc.search_vector @@ websearch_to_tsquery('english', %s)",
        ]
        params: list[Any] = [tenant_id, user_id]
        if filters:
            clauses.append("dc.metadata @> %s::jsonb")
            params.append(json.dumps(filters))
        if sensitivity_ceiling:
            clauses.append(_sensitivity_clause("d"))
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
                ts_rank_cd(dc.search_vector, websearch_to_tsquery('english', %s)) as fts_score
            from document_chunks dc
            join documents d on d.id = dc.document_id
            where {' and '.join(clauses)}
            order by fts_score desc, dc.chunk_index asc
            limit %s
        """
        execution_params = [query_text, tenant_id, user_id, query_text, *params[2:]]
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, execution_params)
                return await cur.fetchall()

    async def diagnose_empty_retrieval(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        query_text: str,
        filters: dict[str, Any],
        sensitivity_ceiling: str | None,
    ) -> str:
        tenant_filters = ["dc.tenant_id = %s", "d.deleted_at is null"]
        accessible_filters = [*tenant_filters, _document_access_clause(alias="d")]
        tenant_params: list[Any] = [tenant_id]
        accessible_params: list[Any] = [tenant_id, user_id]
        if query_text:
            tenant_filters.append("dc.search_vector @@ websearch_to_tsquery('english', %s)")
            accessible_filters.append("dc.search_vector @@ websearch_to_tsquery('english', %s)")
            tenant_params.append(query_text)
            accessible_params.append(query_text)
        if filters:
            tenant_filters.append("dc.metadata @> %s::jsonb")
            accessible_filters.append("dc.metadata @> %s::jsonb")
            encoded = json.dumps(filters)
            tenant_params.append(encoded)
            accessible_params.append(encoded)
        if sensitivity_ceiling:
            tenant_filters.append(_sensitivity_clause("d"))
            accessible_filters.append(_sensitivity_clause("d"))
            tenant_params.append(sensitivity_ceiling)
            accessible_params.append(sensitivity_ceiling)
        tenant_query = f"""
            select exists(
                select 1
                from document_chunks dc
                join documents d on d.id = dc.document_id
                where {' and '.join(tenant_filters)}
            ) as matched
        """
        accessible_query = f"""
            select exists(
                select 1
                from document_chunks dc
                join documents d on d.id = dc.document_id
                where {' and '.join(accessible_filters)}
            ) as matched
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(tenant_query, tenant_params)
                tenant_row = await cur.fetchone()
                await cur.execute(accessible_query, accessible_params)
                accessible_row = await cur.fetchone()
        if bool(tenant_row["matched"]) and not bool(accessible_row["matched"]):
            return "no_access"
        return "no_match"

    async def create_conversation(self, *, tenant_id: UUID, user_id: UUID, title: str) -> UUID:
        query = """
            insert into conversations (tenant_id, user_id, title)
            values (%s, %s, %s)
            returning id
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id, user_id, title))
                row = await cur.fetchone()
                await conn.commit()
                return row["id"]

    async def create_message(
        self,
        *,
        conversation_id: UUID,
        role: str,
        content: str,
        model_profile: str,
        sources: list[dict[str, Any]],
        token_usage: dict[str, Any],
    ) -> UUID:
        query = """
            insert into messages (conversation_id, role, content, model_profile, sources, token_usage)
            values (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
            returning id
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        conversation_id,
                        role,
                        content,
                        model_profile,
                        json.dumps(sources),
                        json.dumps(token_usage),
                    ),
                )
                row = await cur.fetchone()
                await cur.execute(
                    "update conversations set updated_at = now() where id = %s",
                    (conversation_id,),
                )
                await conn.commit()
                return row["id"]

    async def list_conversations(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        limit: int,
    ) -> list[ConversationSummary]:
        query = """
            select id, title, created_at, updated_at
            from conversations
            where tenant_id = %s and user_id = %s
            order by updated_at desc
            limit %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id, user_id, limit))
                rows = await cur.fetchall()
        return [ConversationSummary(**row) for row in rows]

    async def list_conversation_messages(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        user_id: UUID,
    ) -> list[ConversationMessage]:
        query = """
            select m.id, m.role, m.content, m.model_profile, m.sources, m.token_usage, m.created_at
            from messages m
            join conversations c on c.id = m.conversation_id
            where c.tenant_id = %s and c.id = %s and c.user_id = %s
            order by m.created_at asc
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id, conversation_id, user_id))
                rows = await cur.fetchall()
        return [ConversationMessage(**row) for row in rows]

    async def create_feedback(
        self,
        *,
        tenant_id: UUID,
        message_id: UUID,
        user_id: UUID,
        rating: str,
        comments: str | None,
        metadata: dict[str, Any],
    ) -> UUID:
        query = """
            insert into feedback (tenant_id, conversation_id, message_id, user_id, rating, comments, metadata)
            select c.tenant_id, c.id, m.id, %s, %s, %s, %s::jsonb
            from messages m
            join conversations c on c.id = m.conversation_id
            where c.tenant_id = %s and m.id = %s
            returning id
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (user_id, rating, comments, json.dumps(metadata), tenant_id, message_id),
                )
                row = await cur.fetchone()
                await conn.commit()
        if not row:
            raise NotFoundError("Message not found.")
        return row["id"]

    async def list_feedback(
        self,
        *,
        tenant_id: UUID,
        limit: int,
    ) -> list[FeedbackRecord]:
        query = """
            select id, tenant_id, message_id, conversation_id, user_id, rating, comments, metadata, created_at
            from feedback
            where tenant_id = %s
            order by created_at desc
            limit %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id, limit))
                rows = await cur.fetchall()
        return [FeedbackRecord(**row) for row in rows]

    async def usage_summary(
        self,
        *,
        tenant_id: UUID,
        date_from: str | None,
        date_to: str | None,
        group_by: str,
    ) -> UsageSummary:
        time_filters = ["tenant_id = %s"]
        params: list[Any] = [tenant_id]
        if date_from:
            time_filters.append("created_at >= %s::date")
            params.append(date_from)
        if date_to:
            time_filters.append("created_at < (%s::date + interval '1 day')")
            params.append(date_to)
        group_expr = {
            "provider": "provider",
            "operation": "operation",
            "model_profile": "model_profile",
            "day": "to_char(date_trunc('day', created_at), 'YYYY-MM-DD')",
        }.get(group_by, "model_profile")
        summary_query = f"""
            select
                count(*)::int as request_count,
                coalesce(sum(input_tokens), 0)::int as input_tokens,
                coalesce(sum(output_tokens), 0)::int as output_tokens,
                coalesce(sum(estimated_cost_usd), 0)::float as estimated_cost_usd
            from model_usage
            where {' and '.join(time_filters)}
        """
        bucket_query = f"""
            select
                {group_expr} as bucket_key,
                count(*)::int as requests,
                coalesce(sum(input_tokens), 0)::int as input_tokens,
                coalesce(sum(output_tokens), 0)::int as output_tokens,
                coalesce(sum(estimated_cost_usd), 0)::float as estimated_cost_usd
            from model_usage
            where {' and '.join(time_filters)}
            group by bucket_key
            order by estimated_cost_usd desc, requests desc
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(summary_query, params)
                summary_row = await cur.fetchone()
                await cur.execute(bucket_query, params)
                bucket_rows = await cur.fetchall()
        buckets = [
            UsageBucket(
                key=row["bucket_key"] or "unknown",
                requests=row["requests"],
                input_tokens=row["input_tokens"],
                output_tokens=row["output_tokens"],
                estimated_cost_usd=row["estimated_cost_usd"],
            )
            for row in bucket_rows
        ]
        return UsageSummary(
            request_count=summary_row["request_count"],
            input_tokens=summary_row["input_tokens"],
            output_tokens=summary_row["output_tokens"],
            estimated_cost_usd=summary_row["estimated_cost_usd"],
            buckets=buckets,
        )

    async def list_admin_ingestion_jobs(
        self,
        *,
        tenant_id: UUID,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        filters = ["tenant_id = %s"]
        params: list[Any] = [tenant_id]
        if status:
            filters.append("status = %s")
            params.append(status)
        query = f"""
            select id, document_id, status, stage, attempts, error_code, error_message, stats, created_at, finished_at
            from ingestion_jobs
            where {' and '.join(filters)}
            order by created_at desc
            limit %s
        """
        params.append(limit)
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                return await cur.fetchall()

    async def list_audit_logs(
        self,
        *,
        tenant_id: UUID,
        limit: int,
        event_type: str | None = None,
    ) -> list[AuditLogRecord]:
        filters = ["tenant_id = %s"]
        params: list[Any] = [tenant_id]
        if event_type:
            filters.append("event_type = %s")
            params.append(event_type)
        query = f"""
            select id, event_type, details, actor_id, created_at
            from audit_logs
            where {' and '.join(filters)}
            order by created_at desc
            limit %s
        """
        params.append(limit)
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall()
        return [AuditLogRecord(**row) for row in rows]

    async def retrieval_metrics_summary(
        self,
        *,
        tenant_id: UUID,
    ) -> RetrievalMetricsSummary:
        query = """
            select
                count(*)::int as total_messages,
                coalesce(avg(case when token_usage->'retrieval'->>'selected_sources' = '[]' then 1 else 0 end), 0)::float as no_result_rate,
                coalesce(avg(case when token_usage->'retrieval'->>'no_source_reason' = 'no_access' then 1 else 0 end), 0)::float as no_access_rate,
                coalesce(avg(jsonb_array_length(coalesce(token_usage->'retrieval'->'selected_sources', '[]'::jsonb))), 0)::float as avg_selected_sources,
                coalesce(avg(((token_usage->'retrieval'->>'context_tokens'))::numeric), 0)::float as avg_context_tokens
            from messages m
            join conversations c on c.id = m.conversation_id
            where c.tenant_id = %s and m.role = 'assistant'
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id,))
                row = await cur.fetchone()
        return RetrievalMetricsSummary(**row)

    async def create_evaluation_run(
        self,
        *,
        tenant_id: UUID,
        run_type: str,
        model_profile: str,
        metrics: dict[str, Any],
        details: dict[str, Any],
    ) -> UUID:
        query = """
            insert into evaluation_runs (tenant_id, run_type, model_profile, metrics, details)
            values (%s, %s, %s, %s::jsonb, %s::jsonb)
            returning id
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id, run_type, model_profile, json.dumps(metrics), json.dumps(details)))
                row = await cur.fetchone()
                await conn.commit()
        return row["id"]

    async def list_evaluation_runs(
        self,
        *,
        tenant_id: UUID,
        limit: int,
    ) -> list[EvaluationRunSummary]:
        query = """
            select id, tenant_id, run_type, model_profile, metrics, created_at
            from evaluation_runs
            where tenant_id = %s
            order by created_at desc
            limit %s
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id, limit))
                rows = await cur.fetchall()
        return [EvaluationRunSummary(**row) for row in rows]

    async def record_model_usage(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID | None,
        operation: str,
        model_profile: str,
        provider: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        estimated_cost_usd: float,
        details: dict[str, Any],
    ) -> None:
        query = """
            insert into model_usage (
                tenant_id, user_id, operation, model_profile, provider, model_name,
                input_tokens, output_tokens, estimated_cost_usd, details
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        tenant_id,
                        user_id,
                        operation,
                        model_profile,
                        provider,
                        model_name,
                        input_tokens,
                        output_tokens,
                        estimated_cost_usd,
                        json.dumps(details),
                    ),
                )
                await conn.commit()

    async def record_audit_log(
        self,
        *,
        tenant_id: UUID,
        actor_id: UUID,
        event_type: str,
        details: dict[str, Any],
    ) -> None:
        query = """
            insert into audit_logs (tenant_id, actor_id, event_type, details)
            values (%s, %s, %s, %s::jsonb)
        """
        safe_details = redact_payload(details)
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (tenant_id, actor_id, event_type, json.dumps(safe_details)))
                await conn.commit()


def _document_access_clause(alias: str = "d") -> str:
    return f"""(
        not exists (
            select 1 from document_acl_groups dag
            where dag.document_id = {alias}.id
        )
        or exists (
            select 1
            from document_acl_groups dag
            join group_members gm on gm.group_id = dag.group_id and gm.tenant_id = dag.tenant_id
            where dag.document_id = {alias}.id and gm.user_id = %s
        )
    )"""


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def _public_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if not key.startswith("_")}


def _sensitivity_clause(alias: str) -> str:
    return f"""
        case {alias}.sensitivity
            when 'public' then 1
            when 'internal' then 2
            when 'confidential' then 3
            when 'restricted' then 4
            else 2
        end <=
        case %s
            when 'public' then 1
            when 'internal' then 2
            when 'confidential' then 3
            when 'restricted' then 4
            else 4
        end
    """
