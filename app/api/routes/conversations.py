from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import WorkspaceContext, get_workspace_context
from app.api.schemas.conversations import ConversationDetailResponse, ConversationListResponse

router = APIRouter()


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    context: WorkspaceContext = Depends(get_workspace_context),
) -> ConversationListResponse:
    return await context.container.conversation_service.list_conversations(
        workspace_id=context.workspace_id,
        principal=context.principal,
        limit=limit,
    )


@router.get("/conversations/{conversation_id}/messages", response_model=ConversationDetailResponse)
async def get_conversation_messages(
    conversation_id: UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
) -> ConversationDetailResponse:
    return await context.container.conversation_service.get_conversation_messages(
        workspace_id=context.workspace_id,
        conversation_id=conversation_id,
        principal=context.principal,
    )
