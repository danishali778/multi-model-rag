from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import WorkspaceContext, get_workspace_context
from app.api.schemas.feedback import FeedbackCreateRequest, FeedbackCreateResponse

router = APIRouter()


@router.post("/messages/{message_id}/feedback", response_model=FeedbackCreateResponse)
async def create_feedback(
    message_id: UUID,
    payload: FeedbackCreateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
) -> FeedbackCreateResponse:
    return await context.container.feedback_service.create_feedback(
        workspace_id=context.workspace_id,
        message_id=message_id,
        principal=context.principal,
        payload=payload,
    )
