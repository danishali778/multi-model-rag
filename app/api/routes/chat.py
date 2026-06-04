from fastapi import APIRouter, Depends

from app.api.dependencies import WorkspaceContext, get_workspace_context
from app.api.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def answer_question(
    payload: ChatRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
) -> ChatResponse:
    await context.container.rate_limiter.check_request(
        principal=context.principal,
        workspace_id=str(context.workspace_id),
        route_key="/v1/chat",
        profile=payload.profile or "balanced",
    )
    return await context.container.chat_service.answer_question(
        workspace_id=context.workspace_id,
        principal=context.principal,
        payload=payload,
    )
