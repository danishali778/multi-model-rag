from typing import Any


class AppError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class BadRequestError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="bad_request", status_code=400, details=details)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Unauthorized.", details: dict[str, Any] | None = None):
        super().__init__(message, code="unauthorized", status_code=401, details=details)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden.", details: dict[str, Any] | None = None):
        super().__init__(message, code="forbidden", status_code=403, details=details)


class NotFoundError(AppError):
    def __init__(self, message: str = "Not found.", details: dict[str, Any] | None = None):
        super().__init__(message, code="not_found", status_code=404, details=details)


class ProviderUnavailableError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="provider_unavailable", status_code=503, details=details)


class ProviderAuthenticationError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="provider_auth_failed", status_code=503, details=details)


class FeatureNotImplementedError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="not_implemented", status_code=501, details=details)


class IngestionFailedError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="ingestion_failed", status_code=422, details=details)


class RetryableIngestionError(Exception):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class TooManyRequestsError(AppError):
    def __init__(self, message: str = "Rate limit exceeded.", details: dict[str, Any] | None = None):
        super().__init__(message, code="rate_limited", status_code=429, details=details)
