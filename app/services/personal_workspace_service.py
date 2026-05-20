from __future__ import annotations

from uuid import UUID

from app.domain.entities.rag import Principal
from app.storage.models.workspace import PersonalWorkspaceCreateInput
from app.storage.repositories.workspace import WorkspaceRepository


class PersonalWorkspaceService:
    def __init__(self, workspace_repository: WorkspaceRepository):
        self.workspace_repository = workspace_repository

    async def ensure_workspace_for_identity(self, *, user_id: UUID, email: str | None) -> UUID:
        workspace = await self.workspace_repository.get_primary_workspace_for_user(user_id)
        if workspace:
            return workspace.id
        return await self.workspace_repository.create_personal_workspace(
            PersonalWorkspaceCreateInput(user_id=user_id, email=email)
        )

    async def resolve_workspace_for_principal(self, principal: Principal) -> UUID:
        workspace = await self.workspace_repository.get_primary_workspace_for_user(principal.user_id)
        if workspace:
            principal.role = workspace.role or "owner"
            return workspace.id
        workspace_id = await self.workspace_repository.create_personal_workspace(
            PersonalWorkspaceCreateInput(user_id=principal.user_id, email=principal.email)
        )
        principal.role = "owner"
        return workspace_id
