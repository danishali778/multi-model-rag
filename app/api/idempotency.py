from __future__ import annotations

from typing import Any, Awaitable, Callable, TypeVar
from uuid import UUID

from pydantic import BaseModel

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


async def execute_idempotent(
    *,
    idempotency_service,
    idempotency_key: str | None,
    route_key: str,
    user_id: UUID,
    workspace_id: UUID | None,
    request_body: dict[str, Any],
    path_params: dict[str, Any] | None,
    response_model: type[ResponseModelT],
    execute: Callable[[], Awaitable[ResponseModelT]],
    replay_transform: Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    resource_type: str | None = None,
    resource_id_selector: Callable[[ResponseModelT], UUID | None] | None = None,
) -> ResponseModelT:
    if not idempotency_key:
        return await execute()
    return await idempotency_service.execute(
        idempotency_key=idempotency_key,
        route_key=route_key,
        user_id=user_id,
        workspace_id=workspace_id,
        request_body=request_body,
        path_params=path_params,
        response_model=response_model,
        execute=execute,
        replay_transform=replay_transform,
        resource_type=resource_type,
        resource_id_selector=resource_id_selector,
    )
