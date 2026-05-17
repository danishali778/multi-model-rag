from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_principal, get_tenant_access
from app.api.schemas.chat import ChatRequest, ChatResponse
from app.core.container import AppContainer
from app.domain.entities.rag import Principal

router = APIRouter()


@router.post("/tenants/{tenant_id}/chat", response_model=ChatResponse)
async def chat_with_sources(
    tenant_id: UUID,
    payload: ChatRequest,
    principal: Principal = Depends(get_current_principal),
    container: AppContainer = Depends(get_tenant_access),
) -> ChatResponse:
    await container.rate_limiter.check_request(
        principal=principal,
        tenant_id=str(tenant_id),
        route_key="chat",
        profile=payload.model_profile,
    )
    return await container.chat_service.answer_question(tenant_id, principal, payload)
