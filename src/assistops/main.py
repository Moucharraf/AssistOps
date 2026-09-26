import re
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from assistops.approvals import router as approvals_router
from assistops.config import Settings
from assistops.events import EventError, router
from assistops.health import dependency_status
from assistops.observability import configure_logging
from assistops.rate_limits import ConnectorRateLimiter
from assistops.storage import EventStore

logger = structlog.get_logger()
CORRELATION_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        logger.info("application_started", environment=settings.environment)
        yield
        logger.info("application_stopped")

    app = FastAPI(
        title="AssistOps",
        version="0.1.0",
        description="Réception durable et authentifiée des événements du MVP.",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.environment != "production" else None,
    )
    app.state.settings = settings
    app.state.event_store = EventStore(settings)
    app.state.rate_limiter = ConnectorRateLimiter(settings)
    app.include_router(router)
    app.include_router(approvals_router)

    def error(request: Request, status: int, code: str) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={"error": {"code": code, "correlation_id": request.state.correlation_id}},
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        supplied = request.headers.get("X-Correlation-ID", "")
        correlation_id = supplied if CORRELATION_ID.fullmatch(supplied) else str(uuid4())
        request.state.correlation_id = correlation_id
        tokens = structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        started = perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception as exc:
                logger.error("request_failed", error_type=type(exc).__name__)
                response = error(request, 500, "internal_error")
            response.headers["X-Correlation-ID"] = correlation_id
            route = request.scope.get("route")
            logger.info(
                "request_completed",
                method=request.method,
                route=getattr(route, "path", "unmatched"),
                status_code=response.status_code,
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
            return response
        finally:
            structlog.contextvars.reset_contextvars(**tokens)

    @app.exception_handler(EventError)
    async def event_error(request: Request, exc: EventError):
        response = error(request, exc.status, exc.code)
        if exc.retry_after is not None:
            response.headers["Retry-After"] = str(exc.retry_after)
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        response = error(request, exc.status_code, f"http_{exc.status_code}")
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error(request, 422, "invalid_request")

    @app.get("/health/live", tags=["health"])
    async def live():
        return {"status": "ok", "service": "assistops"}

    @app.get("/health/ready", tags=["health"])
    async def ready():
        dependencies = await dependency_status(settings)
        available = all(value == "ok" for value in dependencies.values())
        return JSONResponse(
            status_code=200 if available else 503,
            content={"status": "ready" if available else "not_ready", "dependencies": dependencies},
        )

    return app
