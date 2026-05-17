from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.schemas.common import ErrorBody, ErrorResponse
from app.domain.errors import AppError


def _correlation_id(request: Request) -> str | None:
    return getattr(getattr(request, "state", None), "correlation_id", None)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        body = ErrorResponse(
            error=ErrorBody(
                code=exc.code,
                message=exc.message,
                details=exc.details,
                correlation_id=_correlation_id(request),
            )
        )
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        body = ErrorResponse(
            error=ErrorBody(
                code="validation_error",
                message="Request validation failed.",
                details={"errors": exc.errors()},
                correlation_id=_correlation_id(request),
            )
        )
        return JSONResponse(status_code=422, content=body.model_dump())
