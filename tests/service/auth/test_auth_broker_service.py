import asyncio

from app.api.schemas.auth import AuthUserResponse
from app.core.config import Settings
from app.services.auth_service import SupabaseAuthBrokerService


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        SUPABASE_URL="https://example.supabase.co",
        SUPABASE_AUTH_PUBLIC_KEY="public-key",
        SUPABASE_SERVICE_ROLE_KEY="service-role",
    )


def test_sign_in_parses_session_payload():
    service = SupabaseAuthBrokerService(_settings())

    async def fake_request(method: str, path: str, **kwargs):
        return {
            "access_token": "access",
            "refresh_token": "refresh",
            "token_type": "bearer",
            "user": {"id": "00000000-0000-0000-0000-000000000001", "email": "dev@example.com"},
        }

    service._request = fake_request  # type: ignore[method-assign]
    session = asyncio.run(service.sign_in("dev@example.com", "password123"))

    assert session.access_token == "access"
    assert session.user.email == "dev@example.com"


def test_sign_out_refreshes_when_only_refresh_token_is_available():
    service = SupabaseAuthBrokerService(_settings())

    async def fake_refresh_session(refresh_token: str):
        return type(
            "Session",
            (),
            {
                "access_token": "access",
                "refresh_token": refresh_token,
                "user": AuthUserResponse(id="00000000-0000-0000-0000-000000000001", email="dev@example.com"),
            },
        )()

    calls = []

    async def fake_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        return {}

    service.refresh_session = fake_refresh_session  # type: ignore[method-assign]
    service._request = fake_request  # type: ignore[method-assign]
    response = asyncio.run(service.sign_out(None, "refresh-token"))

    assert response.message == "Signed out."
    assert calls == [("POST", "/logout", {"bearer_token": "access"})]
