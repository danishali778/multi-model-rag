from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_admin_tenant_access
from app.api.schemas.admin import (
    AdminAuditLogListResponse,
    AdminEvaluationRunListResponse,
    AdminEvaluationRunRequest,
    AdminEvaluationRunResponse,
    AdminFeedbackListResponse,
    AdminJobRequeueResponse,
    AdminIngestionJobListResponse,
    AdminRetrievalMetricsResponse,
    AdminUsageResponse,
)
from app.core.container import AppContainer

router = APIRouter()


@router.get("/tenants/{tenant_id}/admin/usage", response_model=AdminUsageResponse)
async def admin_usage(
    tenant_id: UUID,
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    group_by: str = Query(default="model_profile"),
    container: AppContainer = Depends(get_admin_tenant_access),
) -> AdminUsageResponse:
    return await container.admin_service.usage_summary(
        tenant_id=tenant_id,
        date_from=from_date,
        date_to=to_date,
        group_by=group_by,
    )


@router.get("/tenants/{tenant_id}/admin/ingestion-jobs", response_model=AdminIngestionJobListResponse)
async def admin_ingestion_jobs(
    tenant_id: UUID,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    container: AppContainer = Depends(get_admin_tenant_access),
) -> AdminIngestionJobListResponse:
    return await container.admin_service.list_ingestion_jobs(
        tenant_id=tenant_id,
        status=status,
        limit=limit,
    )


@router.post("/tenants/{tenant_id}/admin/ingestion-jobs/{job_id}/requeue", response_model=AdminJobRequeueResponse)
async def admin_requeue_ingestion_job(
    tenant_id: UUID,
    job_id: UUID,
    container: AppContainer = Depends(get_admin_tenant_access),
) -> AdminJobRequeueResponse:
    return await container.admin_service.requeue_dead_letter_job(tenant_id=tenant_id, job_id=job_id)


@router.get("/tenants/{tenant_id}/admin/audit-logs", response_model=AdminAuditLogListResponse)
async def admin_audit_logs(
    tenant_id: UUID,
    event_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    container: AppContainer = Depends(get_admin_tenant_access),
) -> AdminAuditLogListResponse:
    return await container.admin_service.list_audit_logs(
        tenant_id=tenant_id,
        limit=limit,
        event_type=event_type,
    )


@router.get("/tenants/{tenant_id}/admin/retrieval-metrics", response_model=AdminRetrievalMetricsResponse)
async def admin_retrieval_metrics(
    tenant_id: UUID,
    container: AppContainer = Depends(get_admin_tenant_access),
) -> AdminRetrievalMetricsResponse:
    return await container.admin_service.retrieval_metrics(tenant_id=tenant_id)


@router.get("/tenants/{tenant_id}/admin/feedback", response_model=AdminFeedbackListResponse)
async def admin_feedback(
    tenant_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    container: AppContainer = Depends(get_admin_tenant_access),
) -> AdminFeedbackListResponse:
    return await container.admin_service.list_feedback(tenant_id=tenant_id, limit=limit)


@router.get("/tenants/{tenant_id}/admin/evaluation-runs", response_model=AdminEvaluationRunListResponse)
async def admin_evaluation_runs(
    tenant_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_admin_tenant_access),
) -> AdminEvaluationRunListResponse:
    return await container.admin_service.list_evaluation_runs(tenant_id=tenant_id, limit=limit)


@router.post("/tenants/{tenant_id}/admin/evaluation-runs", response_model=AdminEvaluationRunResponse)
async def run_admin_evaluation(
    tenant_id: UUID,
    payload: AdminEvaluationRunRequest,
    container: AppContainer = Depends(get_admin_tenant_access),
) -> AdminEvaluationRunResponse:
    run_id = await container.evaluation_service.run_retrieval_evaluation(
        tenant_id=tenant_id,
        model_profile=payload.model_profile,
    )
    return AdminEvaluationRunResponse(evaluation_run_id=run_id, status="recorded")
