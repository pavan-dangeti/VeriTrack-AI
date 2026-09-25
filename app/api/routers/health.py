"""Liveness (/health) and readiness (/health/ready: Postgres, plus Redis when used; 503 if unreachable)."""

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "veritrack-api"}


async def _check_db() -> bool:
    from app.db.session import get_session_factory

    async with get_session_factory()() as db:
        await db.execute(text("SELECT 1"))
    return True


async def _check_redis() -> bool:
    import redis.asyncio as aioredis

    from app.core.config import settings

    client = aioredis.from_url(settings.celery_broker_url, socket_timeout=1)
    try:
        return bool(await client.ping())
    finally:
        await client.aclose()


def _uses_redis() -> bool:
    from app.core.config import settings

    return settings.processing_mode == "celery" or settings.rate_limit_storage_uri.startswith(
        "redis"
    )


@router.get("/health/ready")
async def ready():
    probes = [_check_db()] + ([_check_redis()] if _uses_redis() else [])
    results = await asyncio.gather(*probes, return_exceptions=True)
    checks = {"db": results[0] is True}
    if len(results) > 1:
        checks["redis"] = results[1] is True
    ok = all(checks.values())
    body = {"status": "ready" if ok else "degraded", "checks": checks}
    return JSONResponse(body, status_code=200 if ok else 503)
