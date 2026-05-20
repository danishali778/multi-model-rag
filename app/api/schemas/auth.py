from pydantic import BaseModel, EmailStr, Field


class AuthUserResponse(BaseModel):
    id: str
    email: EmailStr | None = None
    email_confirmed_at: str | None = None


class AuthSessionResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int | None = None
    expires_at: int | None = None
    token_type: str = "bearer"
    user: AuthUserResponse


class SignInRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class SignUpRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    redirect_to: str | None = None


class SignUpResponse(BaseModel):
    status: str
    message: str
    session: AuthSessionResponse | None = None
    user: AuthUserResponse | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    redirect_to: str | None = None


class RefreshSessionRequest(BaseModel):
    refresh_token: str


class SignOutRequest(BaseModel):
    refresh_token: str | None = None


class AuthCallbackRequest(BaseModel):
    token_hash: str | None = None
    type: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None


class AuthCallbackResponse(BaseModel):
    status: str
    message: str
    session: AuthSessionResponse | None = None
    user: AuthUserResponse | None = None


class UpdatePasswordRequest(BaseModel):
    password: str = Field(min_length=8)


class MessageResponse(BaseModel):
    status: str = "ok"
    message: str
