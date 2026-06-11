from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(slots=True)
class IdempotencyRequestRow:
    id: UUID
    user_id: UUID
    workspace_id: UUID | None
    route_key: str
    idempotency_key: str
    request_hash: str
    status: str
    response_status_code: int | None
    response_body: dict | None
    resource_type: str | None
    resource_id: UUID | None
    locked_at: datetime
    completed_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "IdempotencyRequestRow":
        return cls(**row)
