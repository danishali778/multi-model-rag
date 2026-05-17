from uuid import UUID

from app.domain.entities.rag import Principal
from app.domain.errors import ForbiddenError
from app.security.permissions import require_admin_role
from app.storage.repositories.rag import RagRepository


class TenantService:
    def __init__(self, repository: RagRepository):
        self.repository = repository

    async def list_tenants(self, principal: Principal):
        return await self.repository.list_tenants_for_user(principal.user_id)

    async def require_access(self, principal: Principal, tenant_id: UUID) -> None:
        role = await self.repository.get_tenant_role(principal.user_id, tenant_id)
        if not role:
            raise ForbiddenError("You do not have access to this tenant.")
        principal.role = role

    async def require_admin_access(self, principal: Principal, tenant_id: UUID) -> None:
        role = await self.repository.get_tenant_role(principal.user_id, tenant_id)
        require_admin_role(role)
        principal.role = role
