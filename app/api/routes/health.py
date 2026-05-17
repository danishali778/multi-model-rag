from fastapi import APIRouter, Depends, Response

from app.api.dependencies import get_container
from app.api.schemas.common import HealthResponse, ReadyResponse
from app.core.config import settings
from app.core.container import AppContainer

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", environment=settings.environment)


@router.get("/ready", response_model=ReadyResponse)
async def ready(container: AppContainer = Depends(get_container)) -> ReadyResponse:
    return await container.health_service.readiness()


@router.get("/metrics")
async def metrics(container: AppContainer = Depends(get_container)) -> Response:
    payload, content_type = container.telemetry.metrics_payload()
    return Response(content=payload, media_type=content_type)
