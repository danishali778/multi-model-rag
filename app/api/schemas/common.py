from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: str
    environment: str


class ReadyChecks(BaseModel):
    supabase: str
    redis: str
    model_provider: str


class ReadyResponse(BaseModel):
    status: str
    checks: ReadyChecks
