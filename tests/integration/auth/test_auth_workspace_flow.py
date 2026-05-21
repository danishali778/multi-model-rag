import asyncio
from types import SimpleNamespace

from app.api.routes.auth import sign_in
from app.api.schemas.auth import AuthSessionResponse, AuthUserResponse, SignInRequest


def test_auth_sign_in_flow_provisions_workspace_in_app_stack():
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

    assert response.user.email == "dev@example.com"
    assert calls[0]["email"] == "dev@example.com"
