import asyncio

from app.services.health_service import HealthService


class _HealthyDatabase:
    async def health_check(self) -> bool:
        return True


class _HealthyRouter:
    async def health_check(self) -> bool:
        return True


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
