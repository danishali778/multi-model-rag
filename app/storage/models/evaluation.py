from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EvaluationRunCreateInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: UUID
    run_type: str
    model_profile: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)


@dataclass(slots=True)
class EvaluationRunRow:
    id: UUID
    workspace_id: UUID
    run_type: str
    model_profile: str
    metrics: dict[str, Any]
    details: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "EvaluationRunRow":
        return cls(**row)
