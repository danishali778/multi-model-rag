from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_current_principal, get_tenant_access
from app.api.schemas.feedback import FeedbackCreateRequest, FeedbackCreateResponse
from app.core.container import AppContainer
from app.domain.entities.rag import Principal

router = APIRouter()


@router.post("/tenants/{tenant_id}/messages/{message_id}/feedback", response_model=FeedbackCreateResponse)
async def create_feedback(
    tenant_id: UUID,
    message_id: UUID,
    payload: FeedbackCreateRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    container: AppContainer = Depends(get_tenant_access),
) -> FeedbackCreateResponse:
    return await container.feedback_service.create_feedback(
        tenant_id=tenant_id,
        message_id=message_id,
        principal=principal,
        payload=payload,
        correlation_id=getattr(request.state, "correlation_id", None),
    )
