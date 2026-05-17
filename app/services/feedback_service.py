from __future__ import annotations

from uuid import UUID

from app.api.schemas.feedback import FeedbackCreateRequest, FeedbackCreateResponse
from app.domain.entities.rag import Principal
from app.storage.repositories.rag import RagRepository


class FeedbackService:
    def __init__(self, repository: RagRepository, telemetry):
        self.repository = repository
        self.telemetry = telemetry

    async def create_feedback(
        self,
        *,
        tenant_id: UUID,
        message_id: UUID,
        principal: Principal,
        payload: FeedbackCreateRequest,
        correlation_id: str | None,
    ) -> FeedbackCreateResponse:
        feedback_id = await self.repository.create_feedback(
            tenant_id=tenant_id,
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
        self.telemetry.record_feedback(rating=str(payload.rating))
        await self.repository.record_audit_log(
            tenant_id=tenant_id,
            actor_id=principal.user_id,
            event_type="feedback.recorded",
            details={
                "feedback_id": str(feedback_id),
                "message_id": str(message_id),
                "rating": payload.rating,
                "categories": payload.categories,
            },
        )
        return FeedbackCreateResponse(feedback_id=feedback_id, status="recorded")
