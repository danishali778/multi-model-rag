from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.container import AppContainer
from app.main import create_app


@contextmanager
def build_test_client() -> Iterator[TestClient]:
    original_startup = AppContainer.startup
    original_shutdown = AppContainer.shutdown
    original_storage_url = settings.supabase_storage_url
    original_service_key = settings.supabase_storage_service_key
    original_public_key = settings.supabase_auth_public_key

    async def _noop_startup(self) -> None:
        return None

    async def _noop_shutdown(self) -> None:
        return None

    AppContainer.startup = _noop_startup
    AppContainer.shutdown = _noop_shutdown
    settings.supabase_storage_url = "https://example.supabase.co"
    settings.supabase_storage_service_key = "service-role"
    settings.supabase_auth_public_key = "public-key"

    try:
        app = create_app()
        with TestClient(app) as client:
            yield client
    finally:
        AppContainer.startup = original_startup
        AppContainer.shutdown = original_shutdown
        settings.supabase_storage_url = original_storage_url
        settings.supabase_storage_service_key = original_service_key
        settings.supabase_auth_public_key = original_public_key
