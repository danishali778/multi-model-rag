from __future__ import annotations

from typing import Any

import httpx

from app.api.schemas.auth import (
    AuthCallbackResponse,
    AuthSessionResponse,
    AuthUserResponse,
    MessageResponse,
    SignUpResponse,
)
from app.core.config import Settings
from app.domain.errors import BadRequestError, ProviderUnavailableError, UnauthorizedError


class SupabaseAuthBrokerService:
    def __init__(self, settings: Settings):
        self.settings = settings
        if not settings.supabase_auth_base_url or not settings.supabase_auth_public_key:
            raise ValueError("Supabase Auth broker requires SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY/SUPABASE_ANON_KEY.")
        self.base_url = settings.supabase_auth_base_url
        self.public_key = settings.supabase_auth_public_key

    async def sign_in(self, email: str, password: str) -> AuthSessionResponse:
        payload = await self._request(
            "POST",
            "/token?grant_type=password",
            json={"email": email, "password": password},
        )
        return await self._parse_session(payload)

    async def sign_up(self, email: str, password: str, redirect_to: str | None) -> SignUpResponse:
        payload = await self._request(
            "POST",
            "/signup",
            json={"email": email, "password": password},
            extra_headers=self._redirect_headers(redirect_to),
        )
        session = await self._maybe_parse_session(payload)
        user = session.user if session else self._maybe_parse_user(payload.get("user"))
        if session:
            return SignUpResponse(
                status="authenticated",
                message="Account created and signed in.",
                session=session,
                user=session.user,
            )
        return SignUpResponse(
            status="verification_required",
            message="Account created. Check your email to confirm your address before signing in.",
            user=user,
        )

    async def forgot_password(self, email: str, redirect_to: str | None) -> MessageResponse:
        await self._request(
            "POST",
            "/recover",
            json={"email": email},
            extra_headers=self._redirect_headers(redirect_to),
        )
        return MessageResponse(message="Password reset email sent.")

    async def refresh_session(self, refresh_token: str) -> AuthSessionResponse:
        payload = await self._request(
            "POST",
            "/token?grant_type=refresh_token",
            json={"refresh_token": refresh_token},
        )
        return await self._parse_session(payload)

    async def finalize_callback(
        self,
        *,
        token_hash: str | None,
        challenge_type: str | None,
        access_token: str | None,
        refresh_token: str | None,
    ) -> AuthCallbackResponse:
        if access_token and refresh_token:
            user = await self._get_user(access_token)
            return AuthCallbackResponse(
                status="authenticated",
                message="Authentication complete.",
                session=AuthSessionResponse(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    token_type="bearer",
                    user=user,
                ),
                user=user,
            )
        if token_hash and challenge_type:
            payload = await self._request(
                "POST",
                "/verify",
                json={"token_hash": token_hash, "type": challenge_type},
            )
            session = await self._maybe_parse_session(payload)
            user = session.user if session else self._maybe_parse_user(payload.get("user"))
            status = "authenticated" if session else "verified"
            message = "Authentication complete." if session else "Verification complete. Please sign in."
            return AuthCallbackResponse(status=status, message=message, session=session, user=user)
        raise BadRequestError("Missing callback verification payload.")

    async def update_password(self, access_token: str, password: str) -> MessageResponse:
        await self._request(
            "PUT",
            "/user",
            json={"password": password},
            bearer_token=access_token,
        )
        return MessageResponse(message="Password updated successfully.")

    async def sign_out(self, access_token: str | None, refresh_token: str | None) -> MessageResponse:
        token = access_token
        if not token and refresh_token:
            refreshed = await self.refresh_session(refresh_token)
            token = refreshed.access_token
        if token:
            await self._request("POST", "/logout", bearer_token=token)
        return MessageResponse(message="Signed out.")

    async def _get_user(self, access_token: str) -> AuthUserResponse:
        payload = await self._request("GET", "/user", bearer_token=access_token)
        return self._parse_user(payload)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        bearer_token: str | None = None,
    ) -> dict[str, Any]:
        headers = {
            "apikey": self.public_key,
            "Accept": "application/json",
        }
        if json is not None:
            headers["Content-Type"] = "application/json"
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        if extra_headers:
            headers.update(extra_headers)
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.request(method, f"{self.base_url}{path}", json=json, headers=headers)
        except httpx.RequestError as exc:
            raise ProviderUnavailableError("Supabase Auth is unavailable.", details={"reason": str(exc)}) from exc
        if response.is_error:
            self._raise_for_error(response)
        if not response.content:
            return {}
        data = response.json()
        if not isinstance(data, dict):
            raise ProviderUnavailableError("Supabase Auth returned an invalid response.")
        return data

    def _raise_for_error(self, response: httpx.Response) -> None:
        payload: dict[str, Any] = {}
        try:
            body = response.json()
            if isinstance(body, dict):
                payload = body
        except ValueError:
            payload = {}
        message = (
            payload.get("msg")
            or payload.get("message")
            or payload.get("error_description")
            or payload.get("error")
            or "Authentication request failed."
        )
        details = {"provider_status": response.status_code, "provider_body": payload}
        if response.status_code in {400, 409, 422}:
            raise BadRequestError(str(message), details=details)
        if response.status_code in {401, 403}:
            raise UnauthorizedError(str(message), details=details)
        raise ProviderUnavailableError(str(message), details=details)

    async def _parse_session(self, payload: dict[str, Any]) -> AuthSessionResponse:
        session = await self._maybe_parse_session(payload)
        if not session:
            raise ProviderUnavailableError("Supabase Auth did not return a session.")
        return session

    async def _maybe_parse_session(self, payload: dict[str, Any]) -> AuthSessionResponse | None:
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        if not access_token or not refresh_token:
            return None
        user = self._maybe_parse_user(payload.get("user"))
        if not user:
            user = await self._get_user(str(access_token))
        return AuthSessionResponse(
            access_token=str(access_token),
            refresh_token=str(refresh_token),
            expires_in=self._coerce_int(payload.get("expires_in")),
            expires_at=self._coerce_int(payload.get("expires_at")),
            token_type=str(payload.get("token_type") or "bearer"),
            user=user,
        )

    def _maybe_parse_user(self, payload: Any) -> AuthUserResponse | None:
        if not isinstance(payload, dict):
            return None
        user_id = payload.get("id")
        if not user_id:
            return None
        return AuthUserResponse(
            id=str(user_id),
            email=payload.get("email") or None,
            email_confirmed_at=payload.get("email_confirmed_at"),
        )

    def _parse_user(self, payload: Any) -> AuthUserResponse:
        user = self._maybe_parse_user(payload)
        if not user:
            raise ProviderUnavailableError("Supabase Auth did not return a valid user payload.")
        return user

    def _redirect_headers(self, redirect_to: str | None) -> dict[str, str]:
        if not redirect_to:
            return {}
        return {"redirect_to": redirect_to, "email_redirect_to": redirect_to}

    def _coerce_int(self, value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
