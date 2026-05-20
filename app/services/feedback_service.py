from __future__ import annotations

from uuid import UUID

from app.api.schemas.feedback import FeedbackCreateRequest, FeedbackCreateResponse
from app.domain.entities.rag import Principal
from app.storage.models.audit import AuditLogInput
from app.storage.models.feedback import FeedbackCreateInput
from app.storage.repositories.audit import AuditRepository
from app.storage.repositories.feedback import FeedbackRepository


class FeedbackService:
    def __init__(self, feedback_repository: FeedbackRepository, audit_repository: AuditRepository, telemetry):
        self.feedback_repository = feedback_repository
        self.audit_repository = audit_repository
        self.telemetry = telemetry

    async def create_feedback(
        self,
        *,
        workspace_id: UUID,
        message_id: UUID,
        principal: Principal,
        payload: FeedbackCreateRequest,
        correlation_id: str | None = None,
    ) -> FeedbackCreateResponse:
        feedback_id = await self.feedback_repository.create_feedback(
            FeedbackCreateInput(
                workspace_id=workspace_id,
                message_id=message_id,
                user_id=principal.user_id,
                rating=str(payload.rating),
                comments=payload.comment,
                metadata={
                    "categories": payload.categories,
                    "correlation_id": correlation_id,
                    "auth_method": principal.auth_method,
                },
            )
        )
        self.telemetry.record_feedback(rating=str(payload.rating))
        await self.audit_repository.record_audit_log(
            AuditLogInput(
                workspace_id=workspace_id,
                actor_id=principal.user_id,
                event_type="feedback.recorded",
                details={
                    "feedback_id": str(feedback_id),
                    "message_id": str(message_id),
                    "rating": payload.rating,
                    "categories": payload.categories,
                },
            )
        )
        return FeedbackCreateResponse(feedback_id=feedback_id, status="recorded")
