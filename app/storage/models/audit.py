from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditLogInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: UUID
    actor_id: UUID
    event_type: str
    details: dict[str, Any] = Field(default_factory=dict)
