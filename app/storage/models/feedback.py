from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FeedbackCreateInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: UUID
    message_id: UUID
    user_id: UUID
    rating: str
    comments: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
