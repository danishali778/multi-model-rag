import asyncio

from app.services.health_service import HealthService


class _HealthyDatabase:
    async def health_check(self) -> bool:
        return True


class _HealthyRouter:
    async def health_check(self) -> bool:
        return True


class _UnhealthyDatabase:
    async def health_check(self) -> bool:
        return False


class _UnhealthyRouter:
    async def health_check(self) -> bool:
        return False


class _Settings:
    redis_url = "redis://localhost:6379/0"


def test_health_service_ready(monkeypatch):
    monkeypatch.setattr("app.services.health_service._socket_check", lambda url: True)
    service = HealthService(
        database=_HealthyDatabase(),
        model_router=_HealthyRouter(),
        settings=_Settings(),
    )

    response = asyncio.run(service.readiness())

    assert response.status == "ready"
    assert response.checks.supabase == "ok"
    assert response.checks.redis == "ok"
    assert response.checks.model_provider == "ok"


def test_health_service_degraded_when_dependencies_fail(monkeypatch):
    monkeypatch.setattr("app.services.health_service._socket_check", lambda url: False)
    service = HealthService(
        database=_UnhealthyDatabase(),
        model_router=_UnhealthyRouter(),
        settings=_Settings(),
    )

    response = asyncio.run(service.readiness())

    assert response.status == "degraded"
    assert response.checks.supabase == "unavailable"
    assert response.checks.redis == "unavailable"
    assert response.checks.model_provider == "unavailable"
