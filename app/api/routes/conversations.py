from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_current_principal, get_tenant_access
from app.api.schemas.conversations import ConversationDetailResponse, ConversationListResponse
from app.core.container import AppContainer
from app.domain.entities.rag import Principal

router = APIRouter()


@router.get("/tenants/{tenant_id}/conversations", response_model=ConversationListResponse)
async def list_conversations(
    tenant_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    container: AppContainer = Depends(get_tenant_access),
) -> ConversationListResponse:
    return await container.conversation_service.list_conversations(
        tenant_id=tenant_id,
        principal=principal,
        limit=limit,
    )


@router.get("/tenants/{tenant_id}/conversations/{conversation_id}/messages", response_model=ConversationDetailResponse)
async def list_conversation_messages(
    tenant_id: UUID,
    conversation_id: UUID,
    principal: Principal = Depends(get_current_principal),
    container: AppContainer = Depends(get_tenant_access),
) -> ConversationDetailResponse:
    return await container.conversation_service.get_conversation_messages(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        principal=principal,
    )
