from __future__ import annotations

from uuid import UUID

from app.api.schemas.admin import (
    AdminAuditLogItem,
    AdminAuditLogListResponse,
    AdminFeedbackItem,
    AdminFeedbackListResponse,
    AdminEvaluationRunItem,
    AdminEvaluationRunListResponse,
    AdminJobRequeueResponse,
    AdminIngestionJobItem,
    AdminIngestionJobListResponse,
    AdminRetrievalMetricsResponse,
    AdminUsageBucket,
    AdminUsageResponse,
    AdminUsageTotals,
    TimePeriod,
)
from app.domain.entities.rag import IngestionTaskPayload
from app.domain.errors import BadRequestError
from app.storage.repositories.rag import RagRepository


class AdminService:
    def __init__(self, repository: RagRepository, ingestion_service=None):
        self.repository = repository
        self.ingestion_service = ingestion_service

    async def usage_summary(
        self,
        *,
        tenant_id: UUID,
        date_from: str | None,
        date_to: str | None,
        group_by: str,
    ) -> AdminUsageResponse:
        summary = await self.repository.usage_summary(
            tenant_id=tenant_id,
            date_from=date_from,
            date_to=date_to,
            group_by=group_by,
        )
        return AdminUsageResponse(
            period=TimePeriod(from_date=date_from, to_date=date_to),
            totals=AdminUsageTotals(
                requests=summary.request_count,
                input_tokens=summary.input_tokens,
                output_tokens=summary.output_tokens,
                estimated_cost_usd=summary.estimated_cost_usd,
            ),
            by_group=[
                AdminUsageBucket(
                    key=bucket.key,
                    requests=bucket.requests,
                    input_tokens=bucket.input_tokens,
                    output_tokens=bucket.output_tokens,
                    estimated_cost_usd=bucket.estimated_cost_usd,
                )
                for bucket in summary.buckets
            ],
        )

    async def list_ingestion_jobs(self, *, tenant_id: UUID, status: str | None, limit: int) -> AdminIngestionJobListResponse:
        rows = await self.repository.list_admin_ingestion_jobs(tenant_id=tenant_id, status=status, limit=limit)
        return AdminIngestionJobListResponse(items=[AdminIngestionJobItem(**row) for row in rows])

    async def list_audit_logs(self, *, tenant_id: UUID, limit: int, event_type: str | None) -> AdminAuditLogListResponse:
        rows = await self.repository.list_audit_logs(tenant_id=tenant_id, limit=limit, event_type=event_type)
        return AdminAuditLogListResponse(
            items=[
                AdminAuditLogItem(
                    id=row.id,
                    event_type=row.event_type,
                    details=row.details,
                    actor_id=row.actor_id,
                    created_at=row.created_at,
                )
                for row in rows
            ]
        )

    async def retrieval_metrics(self, *, tenant_id: UUID) -> AdminRetrievalMetricsResponse:
        summary = await self.repository.retrieval_metrics_summary(tenant_id=tenant_id)
        return AdminRetrievalMetricsResponse(
            total_messages=summary.total_messages,
            no_result_rate=summary.no_result_rate,
            no_access_rate=summary.no_access_rate,
            avg_selected_sources=summary.avg_selected_sources,
            avg_context_tokens=summary.avg_context_tokens,
        )

    async def list_feedback(self, *, tenant_id: UUID, limit: int) -> AdminFeedbackListResponse:
        rows = await self.repository.list_feedback(tenant_id=tenant_id, limit=limit)
        return AdminFeedbackListResponse(
            items=[
                AdminFeedbackItem(
                    id=row.id,
                    message_id=row.message_id,
                    conversation_id=row.conversation_id,
                    user_id=row.user_id,
                    rating=row.rating,
                    comments=row.comments,
                    metadata=row.metadata,
                    created_at=row.created_at,
                )
                for row in rows
            ]
        )

    async def list_evaluation_runs(self, *, tenant_id: UUID, limit: int) -> AdminEvaluationRunListResponse:
        rows = await self.repository.list_evaluation_runs(tenant_id=tenant_id, limit=limit)
        return AdminEvaluationRunListResponse(
            items=[
                AdminEvaluationRunItem(
                    id=row.id,
                    tenant_id=row.tenant_id,
                    run_type=row.run_type,
                    model_profile=row.model_profile,
                    metrics=row.metrics,
                    created_at=row.created_at,
                )
                for row in rows
            ]
        )

    async def requeue_dead_letter_job(self, *, tenant_id: UUID, job_id: UUID) -> AdminJobRequeueResponse:
        if self.ingestion_service is None:
            raise RuntimeError("Ingestion service is not configured.")
        row = await self.repository.get_ingestion_job_internal(tenant_id=tenant_id, job_id=job_id)
        if row["status"] not in {"dead_letter", "failed"}:
            raise BadRequestError("Only failed or dead-letter ingestion jobs can be requeued.")
        await self.ingestion_service.requeue_dead_letter_job(
            IngestionTaskPayload(
                tenant_id=tenant_id,
                document_id=row["document_id"],
                job_id=row["id"],
            )
        )
        return AdminJobRequeueResponse(ingestion_job_id=row["id"], status="queued")
