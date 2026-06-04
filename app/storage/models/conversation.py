from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreateInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: UUID
    user_id: UUID
    title: str


class MessageCreateInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation_id: UUID
    role: str
    content: str
    model_profile: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    token_usage: dict[str, Any] = Field(default_factory=dict)


@dataclass(slots=True)
class ConversationSummaryRow:
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "ConversationSummaryRow":
        return cls(**row)


@dataclass(slots=True)
class ConversationRow:
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "ConversationRow":
        return cls(**row)


@dataclass(slots=True)
class ConversationMessageRow:
    id: UUID
    role: str
    content: str
    model_profile: str | None
    sources: list[dict[str, Any]]
    token_usage: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "ConversationMessageRow":
        return cls(**row)
