from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelUsageInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: UUID
    user_id: UUID | None = None
    operation: str
    model_profile: str
    provider: str
    model_name: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    details: dict[str, Any] = Field(default_factory=dict)
