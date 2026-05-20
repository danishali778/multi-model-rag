from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConnectorCheckpointUpsertInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: UUID
    connector_type: str
    source_key: str
    cursor: dict[str, Any] = Field(default_factory=dict)
    status: str
    error_message: str | None = None
