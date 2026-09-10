"""Health endpoints.

/health        — liveness only (cheap, no dependencies)
/health/ready  — readiness: actually probes Postgres and Redis; 503 when either
                 is unreachable so orchestrators stop routing traffic.
"""

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


@router.get("/health/ready")
async def ready():
    results = await asyncio.gather(
        _check_db(), _check_redis(), return_exceptions=True
    )
    checks = {"db": results[0] is True, "redis": results[1] is True}
    ok = all(checks.values())
    body = {"status": "ready" if ok else "degraded", "checks": checks}
    return JSONResponse(body, status_code=200 if ok else 503)
