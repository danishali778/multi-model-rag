import asyncio
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest

from app.core.config import Settings
from app.domain.errors import UnauthorizedError
from app.security.auth import AuthService


def test_api_key_authentication():
    settings = Settings(api_key="secret-key", dev_user_id="00000000-0000-0000-0000-000000000001")
    service = AuthService(settings)
    principal = asyncio.run(service.authenticate(None, "secret-key"))
    assert principal.auth_method == "api_key"


def test_api_key_disabled_outside_development(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOW_DEV_API_KEY", "false")
    settings = Settings(
        _env_file=None,
        api_key="secret-key",
        dev_user_id="00000000-0000-0000-0000-000000000001",
    )
    service = AuthService(settings)
    try:
        asyncio.run(service.authenticate(None, "secret-key"))
    except Exception as exc:  # noqa: BLE001
        assert str(exc) == "Invalid or missing credentials."
    else:  # pragma: no cover
        raise AssertionError("API key auth should be disabled outside development")


def test_jwt_authentication():
    secret = "jwt-secret-key-with-at-least-thirty-two-bytes"
    user_id = str(uuid4())
    settings = Settings(
        _env_file=None,
        supabase_jwks_url="https://example.com/jwks",
        supabase_jwt_algorithm="HS256",
        supabase_jwt_audience="authenticated",
    )
    service = AuthService(settings)
    service.__dict__["jwk_client"] = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=secret)
    )
    token = jwt.encode(
        {"sub": user_id, "email": "jwt@example.com", "aud": "authenticated"},
        secret,
        algorithm="HS256",
    )

    principal = asyncio.run(service.authenticate(f"Bearer {token}", None))

    assert principal.auth_method == "jwt"
    assert str(principal.user_id) == user_id
    assert principal.email == "jwt@example.com"


@pytest.mark.parametrize(
    ("claims", "secret", "expected_message"),
    [
        ({"sub": str(uuid4()), "email": "jwt@example.com", "aud": "wrong"}, "jwt-secret-key-with-at-least-thirty-two-bytes", "Invalid JWT."),
        ({"email": "jwt@example.com", "aud": "authenticated"}, "jwt-secret-key-with-at-least-thirty-two-bytes", "JWT is missing the subject claim."),
        ({"sub": "not-a-uuid", "email": "jwt@example.com", "aud": "authenticated"}, "jwt-secret-key-with-at-least-thirty-two-bytes", "JWT subject is not a valid UUID."),
    ],
)
def test_jwt_authentication_rejects_invalid_claims(claims, secret, expected_message):
    settings = Settings(
        _env_file=None,
        supabase_jwks_url="https://example.com/jwks",
        supabase_jwt_algorithm="HS256",
        supabase_jwt_audience="authenticated",
    )
    service = AuthService(settings)
    service.__dict__["jwk_client"] = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=secret)
    )
    token = jwt.encode(claims, secret, algorithm="HS256")

    with pytest.raises(UnauthorizedError, match=expected_message):
        asyncio.run(service.authenticate(f"Bearer {token}", None))


def test_jwt_authentication_rejects_invalid_signature():
    settings = Settings(
        _env_file=None,
        supabase_jwks_url="https://example.com/jwks",
        supabase_jwt_algorithm="HS256",
        supabase_jwt_audience="authenticated",
    )
    service = AuthService(settings)
    service.__dict__["jwk_client"] = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key="jwt-secret-key-with-at-least-thirty-two-bytes")
    )
    token = jwt.encode(
        {"sub": str(uuid4()), "email": "jwt@example.com", "aud": "authenticated"},
        "different-secret-key-with-at-least-thirty-two-bytes",
        algorithm="HS256",
    )

    with pytest.raises(UnauthorizedError, match="Invalid JWT."):
        asyncio.run(service.authenticate(f"Bearer {token}", None))
