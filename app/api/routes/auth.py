from uuid import UUID

from fastapi import APIRouter, Depends, Header

from app.api.dependencies import get_container
from app.api.schemas.auth import (
    AuthCallbackRequest,
    AuthCallbackResponse,
    AuthSessionResponse,
    ForgotPasswordRequest,
    MessageResponse,
    RefreshSessionRequest,
    SignInRequest,
    SignOutRequest,
    SignUpRequest,
    SignUpResponse,
    UpdatePasswordRequest,
)
from app.core.container import AppContainer
from app.domain.errors import UnauthorizedError

router = APIRouter(prefix="/auth")


@router.post("/sign-in", response_model=AuthSessionResponse)
async def sign_in(payload: SignInRequest, container: AppContainer = Depends(get_container)) -> AuthSessionResponse:
    session = await container.supabase_auth_service.sign_in(payload.email, payload.password)
    await container.personal_workspace_service.ensure_workspace_for_identity(user_id=UUID(session.user.id), email=session.user.email)
    return session


@router.post("/sign-up", response_model=SignUpResponse)
async def sign_up(payload: SignUpRequest, container: AppContainer = Depends(get_container)) -> SignUpResponse:
    response = await container.supabase_auth_service.sign_up(payload.email, payload.password, payload.redirect_to)
    if response.user:
        await container.personal_workspace_service.ensure_workspace_for_identity(user_id=UUID(response.user.id), email=response.user.email)
    return response


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    container: AppContainer = Depends(get_container),
) -> MessageResponse:
    return await container.supabase_auth_service.forgot_password(payload.email, payload.redirect_to)


@router.post("/refresh", response_model=AuthSessionResponse)
async def refresh_session(
    payload: RefreshSessionRequest,
    container: AppContainer = Depends(get_container),
) -> AuthSessionResponse:
    return await container.supabase_auth_service.refresh_session(payload.refresh_token)


@router.post("/callback", response_model=AuthCallbackResponse)
async def finalize_callback(
    payload: AuthCallbackRequest,
    container: AppContainer = Depends(get_container),
) -> AuthCallbackResponse:
    response = await container.supabase_auth_service.finalize_callback(
        token_hash=payload.token_hash,
        challenge_type=payload.type,
        access_token=payload.access_token,
        refresh_token=payload.refresh_token,
    )
    if response.user:
        await container.personal_workspace_service.ensure_workspace_for_identity(user_id=UUID(response.user.id), email=response.user.email)
    return response


@router.post("/update-password", response_model=MessageResponse)
async def update_password(
    payload: UpdatePasswordRequest,
    authorization: str | None = Header(default=None),
    container: AppContainer = Depends(get_container),
) -> MessageResponse:
    access_token = _extract_bearer_token(authorization)
    return await container.supabase_auth_service.update_password(access_token, payload.password)


@router.post("/sign-out", response_model=MessageResponse)
async def sign_out(
    payload: SignOutRequest,
    authorization: str | None = Header(default=None),
    container: AppContainer = Depends(get_container),
) -> MessageResponse:
    access_token = _extract_bearer_token(authorization, required=False)
    return await container.supabase_auth_service.sign_out(access_token, payload.refresh_token)


def _extract_bearer_token(authorization: str | None, *, required: bool = True) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    if required:
        raise UnauthorizedError("Missing bearer token.")
    return None
