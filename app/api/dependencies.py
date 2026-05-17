from collections.abc import AsyncIterator
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
        tenant_id=None,
        route_key=request.url.path,
    )
    return principal


async def get_tenant_access(
    request: Request,
    tenant_id: UUID,
    principal: Principal = Depends(get_current_principal),
) -> AppContainer:
    container: AppContainer = request.app.state.container
    await container.tenant_service.require_access(principal, tenant_id)
    await container.rate_limiter.check_request(
        principal=principal,
        tenant_id=str(tenant_id),
        route_key=request.url.path,
    )
    return container


async def get_admin_tenant_access(
    request: Request,
    tenant_id: UUID,
    principal: Principal = Depends(get_current_principal),
) -> AppContainer:
    container: AppContainer = request.app.state.container
    await container.tenant_service.require_admin_access(principal, tenant_id)
    await container.rate_limiter.check_request(
        principal=principal,
        tenant_id=str(tenant_id),
        route_key=f"admin:{request.url.path}",
    )
    return container
