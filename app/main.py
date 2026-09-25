import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routers import (
    analysis,
    analytics,
    audit,
    auth,
    dashboard,
    employees,
    health,
    leaves,
    uploads,
    users,
)
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.proxy import TrustedProxyMiddleware
from app.core.rate_limit import limiter
from app.db.session import engine

log = get_logger("http")


class RequestContextLogMiddleware(BaseHTTPMiddleware):
    """Binds a request id (a sane inbound X-Request-ID, else generated) to log lines and error envelopes."""

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request_id = (
            incoming
            if 8 <= len(incoming) <= 64 and incoming.replace("-", "").isalnum()
            else uuid.uuid4().hex[:12]
        )
        started = time.perf_counter()
        from structlog import contextvars as sctx

        sctx.clear_contextvars()
        sctx.bind_contextvars(request_id=request_id)
        request.state.request_id = request_id
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
    try:
        from structlog import contextvars as sctx

        rid = sctx.get_contextvars().get("request_id")
        if rid:
            err["request_id"] = rid
    except Exception:  # noqa: S110 — context may be unset outside a request
        pass
    return {"error": err}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info(
        "startup",
        environment=settings.environment,
        m365_sso_enabled=settings.m365_enabled,
        processing_mode=settings.processing_mode,
    )
    from app.services import jobs
    from app.services.storage import get_storage

    get_storage()  # fail fast on a storage misconfiguration, not at first upload
    if settings.processing_mode == "background" and settings.ocr_engine in ("auto", "rapid"):
        # load the OCR models now, off the event loop, so the first upload
        # after a deploy is not the one that pays the model start-up cost
        import asyncio

        from app.services.extraction.gets_grid import warm_up_ocr

        asyncio.get_running_loop().run_in_executor(None, warm_up_ocr)
    try:
        await jobs.recover_interrupted_batches()
        await jobs.recover_interrupted_analyses()
    except Exception as exc:  # noqa: BLE001 — DB may be migrating; not fatal
        log.warning("recovery_skipped", error=str(exc)[:200])
    yield
    await jobs.drain()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="VeriTrack AI API",
        version="2.0.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
        max_age=600,
    )
    app.add_middleware(RequestContextLogMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(TrustedProxyMiddleware, hops=settings.trusted_proxy_hops)

    app.state.limiter = limiter
    limiter.enabled = True

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(audit.router, prefix="/api/v1")
    app.include_router(uploads.router, prefix="/api/v1")
    app.include_router(employees.router, prefix="/api/v1")
    app.include_router(analysis.router, prefix="/api/v1")
    app.include_router(dashboard.router, prefix="/api/v1")
    app.include_router(analytics.router, prefix="/api/v1")
    app.include_router(leaves.router, prefix="/api/v1")

    @app.exception_handler(RateLimitExceeded)
    async def rate_limited(_: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content=_error("rate_limited", f"Too many requests ({exc.detail})"),
            headers={"Retry-After": "60"},
        )

    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Covers FastAPI HTTPException AND framework-level errors like the
        # router's own 404 ("unmapped path") — one envelope for everything.
        detail = exc.detail
        if isinstance(detail, dict):
            code = detail.get("code", "http_error")
            message = detail.get("message", "Request failed")
        else:
            code = "http_error" if exc.status_code >= 500 else "not_found" if exc.status_code == 404 else "http_error"
            message = str(detail)
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

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Last-resort 500: never leak tracebacks — log them, return the id."""
        log.error("unhandled_exception", path=request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_error(
                "internal_error",
                "Something went wrong on our side. Reference the request ID when reporting.",
            ),
        )

    return app


app = create_app()
