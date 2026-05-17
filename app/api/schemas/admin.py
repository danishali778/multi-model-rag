from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class TimePeriod(BaseModel):
    from_date: str | None = Field(default=None, alias="from")
    to_date: str | None = Field(default=None, alias="to")

    model_config = {"populate_by_name": True}


class AdminUsageTotals(BaseModel):
    requests: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class AdminUsageBucket(BaseModel):
    key: str
    requests: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class AdminUsageResponse(BaseModel):
    period: TimePeriod
    totals: AdminUsageTotals
    by_group: list[AdminUsageBucket]


class AdminIngestionJobItem(BaseModel):
    id: UUID
    document_id: UUID
    status: str
    stage: str | None = None
    attempts: int
    error_code: str | None = None
    error_message: str | None = None
    stats: dict[str, Any]
    created_at: datetime
    finished_at: datetime | None = None


class AdminIngestionJobListResponse(BaseModel):
    items: list[AdminIngestionJobItem]


class AdminAuditLogItem(BaseModel):
    id: UUID
    event_type: str
    details: dict[str, Any]
    actor_id: UUID | None = None
    created_at: datetime


class AdminAuditLogListResponse(BaseModel):
    items: list[AdminAuditLogItem]


class AdminRetrievalMetricsResponse(BaseModel):
    total_messages: int
    no_result_rate: float
    no_access_rate: float
    avg_selected_sources: float
    avg_context_tokens: float


class AdminFeedbackItem(BaseModel):
    id: UUID
    message_id: UUID | None = None
    conversation_id: UUID | None = None
    user_id: UUID | None = None
    rating: str | None = None
    comments: str | None = None
    metadata: dict[str, Any]
    created_at: datetime


class AdminFeedbackListResponse(BaseModel):
    items: list[AdminFeedbackItem]


class AdminEvaluationRunItem(BaseModel):
    id: UUID
    tenant_id: UUID
    run_type: str
    model_profile: str
    metrics: dict[str, Any]
    created_at: datetime


class AdminEvaluationRunListResponse(BaseModel):
    items: list[AdminEvaluationRunItem]


class AdminEvaluationRunRequest(BaseModel):
    model_profile: str = "balanced"


class AdminEvaluationRunResponse(BaseModel):
    evaluation_run_id: UUID
    status: str


class AdminJobRequeueResponse(BaseModel):
    ingestion_job_id: UUID
    status: str
