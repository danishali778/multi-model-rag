from uuid import uuid4

import structlog
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.schemas.common import ErrorBody, ErrorResponse
from app.core.telemetry import Timer
from app.domain.errors import BadRequestError


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid4()))
        request.state.correlation_id = correlation_id
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        structlog.contextvars.clear_contextvars()
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, max_body_bytes: int):
        super().__init__(app)
        self.max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_body_bytes:
            error = BadRequestError(
                "Request body is too large.",
                details={"max_body_bytes": self.max_body_bytes},
            )
            correlation_id = request.headers.get("X-Correlation-ID")
            body = ErrorResponse(
                error=ErrorBody(
                    code=error.code,
                    message=error.message,
                    details=error.details,
                    correlation_id=correlation_id,
                )
            )
            response = JSONResponse(status_code=error.status_code, content=body.model_dump())
            if correlation_id:
                response.headers["X-Correlation-ID"] = correlation_id
            return response
        return await call_next(request)


class TelemetryMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        container = getattr(request.app.state, "container", None)
        if container is None:
            return await call_next(request)
        telemetry = container.telemetry
        timer = Timer()
        with telemetry.tracer("http").start_as_current_span(f"{request.method} {request.url.path}") as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.route", request.url.path)
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
        telemetry.record_http_request(
            method=request.method,
            route=request.url.path,
            status_code=response.status_code,
            duration_seconds=timer.elapsed_seconds,
        )
        return response
