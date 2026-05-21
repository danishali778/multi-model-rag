import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.routes.auth import sign_in, sign_out, update_password
from app.api.schemas.auth import (
    AuthSessionResponse,
    AuthUserResponse,
    MessageResponse,
    SignInRequest,
    SignOutRequest,
    SignUpRequest,
    UpdatePasswordRequest,
)
from app.domain.errors import UnauthorizedError


def test_sign_in_returns_session_and_provisions_workspace():
    calls = []

    async def fake_sign_in(email: str, password: str):
        return AuthSessionResponse(
            access_token="access",
            refresh_token="refresh",
            token_type="bearer",
            user=AuthUserResponse(id="00000000-0000-0000-0000-000000000001", email=email),
        )

    async def fake_ensure_workspace_for_identity(**kwargs):
        calls.append(kwargs)
        return "workspace-id"

    container = SimpleNamespace(
        supabase_auth_service=SimpleNamespace(sign_in=fake_sign_in),
        personal_workspace_service=SimpleNamespace(ensure_workspace_for_identity=fake_ensure_workspace_for_identity),
    )

    response = asyncio.run(sign_in(SignInRequest(email="dev@example.com", password="password123"), container))

    assert response.access_token == "access"
    assert calls[0]["email"] == "dev@example.com"


def test_update_password_requires_bearer_token():
    with pytest.raises(UnauthorizedError):
        asyncio.run(
            update_password(
                UpdatePasswordRequest(password="new-password123"),
                authorization=None,
                container=SimpleNamespace(),
            )
        )


def test_sign_up_schema_rejects_short_password():
    with pytest.raises(ValidationError):
        SignUpRequest(email="dev@example.com", password="short")


def test_sign_out_accepts_optional_bearer_token():
    async def fake_sign_out(access_token: str | None, refresh_token: str | None):
        return MessageResponse(message="Signed out.")

    container = SimpleNamespace(supabase_auth_service=SimpleNamespace(sign_out=fake_sign_out))
    response = asyncio.run(
        sign_out(
            SignOutRequest(refresh_token="refresh-token"),
            authorization="Bearer access-token",
            container=container,
        )
    )

    assert response.message == "Signed out."
