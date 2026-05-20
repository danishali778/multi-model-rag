from fastapi import APIRouter, Depends

from app.api.dependencies import WorkspaceContext, get_workspace_context
from app.api.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def answer_question(
    payload: ChatRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
) -> ChatResponse:
    return await context.container.chat_service.answer_question(
        workspace_id=context.workspace_id,
        principal=context.principal,
        payload=payload,
    )
