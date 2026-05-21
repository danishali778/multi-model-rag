from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass
class RecordingWorkspaceRepository:
    primary_workspace: object | None = None
    created_payloads: list[object] = field(default_factory=list)

    async def get_primary_workspace_for_user(self, user_id: UUID):
        return self.primary_workspace

    async def create_personal_workspace(self, payload):
        self.created_payloads.append(payload)
        return uuid4()
