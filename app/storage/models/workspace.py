from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PersonalWorkspaceCreateInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    email: str | None = None


@dataclass(slots=True)
class WorkspaceAccessRow:
    id: UUID
    name: str
    slug: str
    role: str

    @classmethod
    def from_row(cls, row: dict) -> "WorkspaceAccessRow":
        return cls(id=row["id"], name=row["name"], slug=row["slug"], role=row["role"])
