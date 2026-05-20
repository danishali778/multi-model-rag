from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, Request

from app.core.container import AppContainer
from app.domain.entities.rag import Principal


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


async def get_current_principal(
    request: Request,
    container: AppContainer = Depends(get_container),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Principal:
    principal = await container.auth_service.authenticate(authorization=authorization, x_api_key=x_api_key)
    await container.rate_limiter.check_request(
        principal=principal,
        workspace_id=None,
        route_key=request.url.path,
    )
    return principal


@dataclass(slots=True)
class WorkspaceContext:
    container: AppContainer
    principal: Principal
    workspace_id: UUID


async def get_workspace_context(
    request: Request,
    principal: Principal = Depends(get_current_principal),
    container: AppContainer = Depends(get_container),
) -> WorkspaceContext:
    workspace_id = await container.personal_workspace_service.resolve_workspace_for_principal(principal)
    await container.rate_limiter.check_request(
        principal=principal,
        workspace_id=str(workspace_id),
        route_key=request.url.path,
    )
    return WorkspaceContext(container=container, principal=principal, workspace_id=workspace_id)
