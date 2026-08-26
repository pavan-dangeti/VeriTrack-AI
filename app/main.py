"""FastAPI application factory."""

import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routers import analysis, audit, auth, employees, health, uploads, users
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.rate_limit import limiter
from app.db.session import engine

log = get_logger("http")


class RequestContextLogMiddleware(BaseHTTPMiddleware):
    """Binds a request id to every log line; logs method/path/status/duration."""

    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        try:
            from structlog import contextvars as sctx

            sctx.bind_contextvars(request_id=request_id)
        except Exception:  # noqa: S110 — logging context is best-effort
            pass
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response


def _error(code: str, message: str, extra: dict[str, Any] | None = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if extra:
        err["details"] = extra
    return {"error": err}


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info(
        "startup",
        environment=settings.environment,
        m365_sso_enabled=settings.m365_enabled,
    )
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="VeriTrack AI API",
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # Explicit origins only — never wildcard (enforced by config validator too).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
        max_age=600,
    )
    app.add_middleware(RequestContextLogMiddleware)

    app.state.limiter = limiter
    limiter.enabled = True

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(audit.router, prefix="/api/v1")
    app.include_router(uploads.router, prefix="/api/v1")
    app.include_router(employees.router, prefix="/api/v1")
    app.include_router(analysis.router, prefix="/api/v1")

    @app.exception_handler(RateLimitExceeded)
    async def rate_limited(_: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content=_error("rate_limited", f"Too many requests ({exc.detail})"),
            headers={"Retry-After": "60"},
        )

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict):
            code = detail.get("code", "http_error")
            message = detail.get("message", "Request failed")
        else:
            code, message = "http_error", str(detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error(code, message),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error(
                "validation_error",
                "Request validation failed",
                [{"loc": ".".join(str(p) for p in e.get("loc", [])), "msg": e.get("msg")}
                 for e in exc.errors()],
            ),
        )

    return app


app = create_app()
