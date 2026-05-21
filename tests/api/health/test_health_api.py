import asyncio
from types import SimpleNamespace

from app.api.routes.health import health, metrics, ready
from app.api.schemas.common import ReadyChecks, ReadyResponse


def test_health_route_returns_environment_payload():
    response = asyncio.run(health())

    assert response.status == "ok"
    assert isinstance(response.environment, str)


def test_ready_route_delegates_to_health_service():
    expected = ReadyResponse(
        status="ready",
        checks=ReadyChecks(supabase="ok", redis="ok", model_provider="ok"),
    )

    async def fake_readiness():
        return expected

    response = asyncio.run(ready(SimpleNamespace(health_service=SimpleNamespace(readiness=fake_readiness))))

    assert response == expected


def test_metrics_route_returns_payload_and_content_type():
    container = SimpleNamespace(telemetry=SimpleNamespace(metrics_payload=lambda: (b"metric 1\n", "text/plain")))

    response = asyncio.run(metrics(container))

    assert response.body == b"metric 1\n"
    assert response.media_type == "text/plain"
