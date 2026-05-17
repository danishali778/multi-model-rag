import socket
from urllib.parse import urlparse

from app.api.schemas.common import ReadyChecks, ReadyResponse
from app.core.config import Settings
from app.llm.router import ModelRouter
from app.storage.db.session import Database


class HealthService:
    def __init__(self, *, database: Database, model_router: ModelRouter, telemetry=None, settings: Settings):
        self.database = database
        self.model_router = model_router
        self.telemetry = telemetry
        self.settings = settings

    async def readiness(self) -> ReadyResponse:
        supabase_ok = await self.database.health_check()
        redis_ok = _socket_check(self.settings.redis_url)
        model_ok = await self.model_router.health_check()
        checks = ReadyChecks(
            supabase="ok" if supabase_ok else "unavailable",
            redis="ok" if redis_ok else "unavailable",
            model_provider="ok" if model_ok else "unavailable",
        )
        overall = "ready" if all(value == "ok" for value in checks.model_dump().values()) else "degraded"
        return ReadyResponse(status=overall, checks=checks)


def _socket_check(redis_url: str) -> bool:
    try:
        parsed = urlparse(redis_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False
