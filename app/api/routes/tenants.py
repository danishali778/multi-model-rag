from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_principal, get_container
from app.api.schemas.tenants import TenantListResponse
from app.core.container import AppContainer
from app.domain.entities.rag import Principal

router = APIRouter()


@router.get("/tenants", response_model=TenantListResponse)
async def list_tenants(
    principal: Principal = Depends(get_current_principal),
    container: AppContainer = Depends(get_container),
) -> TenantListResponse:
    items = await container.tenant_service.list_tenants(principal)
    return TenantListResponse(items=items)
