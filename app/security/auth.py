from functools import cached_property
from typing import Any
from uuid import UUID

import jwt
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientError

from app.core.config import Settings
from app.domain.entities.rag import Principal
from app.domain.errors import UnauthorizedError


class AuthService:
    def __init__(self, settings: Settings):
        self.settings = settings

    @cached_property
    def jwk_client(self) -> PyJWKClient | None:
        if not self.settings.supabase_jwks_url:
            return None
        return PyJWKClient(str(self.settings.supabase_jwks_url))

    async def authenticate(self, authorization: str | None, x_api_key: str | None) -> Principal:
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
            return self._authenticate_jwt(token)
        if x_api_key and self.settings.dev_api_key_enabled and x_api_key == self.settings.api_key:
            return Principal(
                user_id=UUID(self.settings.dev_user_id),
                email=self.settings.dev_user_email,
                auth_method="api_key",
                role="owner",
                claims={},
            )
        raise UnauthorizedError("Invalid or missing credentials.")

    def _authenticate_jwt(self, token: str) -> Principal:
        if not self.jwk_client:
            raise UnauthorizedError("JWT authentication is not configured.")
        try:
            signing_key = self.jwk_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=[self.settings.supabase_jwt_algorithm],
                audience=self.settings.supabase_jwt_audience,
            )
        except (InvalidTokenError, PyJWKClientError) as exc:
            raise UnauthorizedError("Invalid JWT.") from exc
        subject = claims.get("sub")
        if not subject:
            raise UnauthorizedError("JWT is missing the subject claim.")
        try:
            user_id = UUID(subject)
        except ValueError as exc:
            raise UnauthorizedError("JWT subject is not a valid UUID.") from exc
        return Principal(
            user_id=user_id,
            email=claims.get("email"),
            auth_method="jwt",
            role=claims.get("role"),
            claims=claims,
        )
