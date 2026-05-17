from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.routes import admin, chat, conversations, documents, feedback, health, tenants
from app.core.config import settings
from app.core.container import AppContainer
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware, RequestSizeLimitMiddleware, TelemetryMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    container = AppContainer(settings)
    await container.startup()
    app.state.container = container
    try:
        yield
    finally:
        await container.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware, max_body_bytes=settings.max_request_body_bytes)
    app.add_middleware(TelemetryMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(tenants.router, prefix="/v1", tags=["tenants"])
    app.include_router(documents.router, prefix="/v1", tags=["documents"])
    app.include_router(chat.router, prefix="/v1", tags=["chat"])
    app.include_router(conversations.router, prefix="/v1", tags=["conversations"])
    app.include_router(feedback.router, prefix="/v1", tags=["feedback"])
    app.include_router(admin.router, prefix="/v1", tags=["admin"])
    return app


app = create_app()
