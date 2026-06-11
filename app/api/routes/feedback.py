from uuid import UUID

from fastapi import APIRouter, Depends, Header

from app.api.dependencies import WorkspaceContext, get_workspace_context
from app.api.idempotency import execute_idempotent
from app.api.schemas.feedback import FeedbackCreateRequest, FeedbackCreateResponse

router = APIRouter()


@router.post("/messages/{message_id}/feedback", response_model=FeedbackCreateResponse)
async def create_feedback(
    message_id: UUID,
    payload: FeedbackCreateRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> FeedbackCreateResponse:
    return await execute_idempotent(
        idempotency_service=context.container.idempotency_service,
        idempotency_key=idempotency_key,
        route_key="/v1/messages/{message_id}/feedback",
        user_id=context.principal.user_id,
        workspace_id=context.workspace_id,
        request_body=payload.model_dump(mode="json"),
        path_params={"message_id": message_id},
        response_model=FeedbackCreateResponse,
        execute=lambda: context.container.feedback_service.create_feedback(
            workspace_id=context.workspace_id,
            message_id=message_id,
            principal=context.principal,
            payload=payload,
        ),
        resource_type="feedback",
        resource_id_selector=lambda response: response.feedback_id,
    )
