from uuid import UUID

from app.domain.entities.rag import Principal
from app.domain.errors import ForbiddenError

ADMIN_ROLES = {"owner", "admin"}


def tenant_scope(principal: Principal, tenant_id: UUID) -> dict[str, str]:
    return {"principal_id": str(principal.user_id), "tenant_id": str(tenant_id)}


def require_role(role: str | None, allowed_roles: set[str]) -> None:
    if role not in allowed_roles:
        raise ForbiddenError("You do not have permission to perform this action.")


def require_admin_role(role: str | None) -> None:
    require_role(role, ADMIN_ROLES)
