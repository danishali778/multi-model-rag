from fastapi import APIRouter, Depends, Header

from app.api.dependencies import WorkspaceContext, get_workspace_context
from app.api.idempotency import execute_idempotent
from app.api.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def answer_question(
    payload: ChatRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ChatResponse:
    return await execute_idempotent(
        idempotency_service=context.container.idempotency_service,
        idempotency_key=idempotency_key,
        route_key="/v1/chat",
        user_id=context.principal.user_id,
        workspace_id=context.workspace_id,
        request_body=payload.model_dump(mode="json"),
        path_params=None,
        response_model=ChatResponse,
        execute=lambda: _execute_chat(context, payload),
        resource_type="chat_message",
        resource_id_selector=lambda response: response.message_id,
    )


async def _execute_chat(context: WorkspaceContext, payload: ChatRequest) -> ChatResponse:
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
