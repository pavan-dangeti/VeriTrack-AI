from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    # Liveness only. A DB-ping variant can live behind a load-balancer-specific
    # path when an orchestrator actually needs it.
    return {"status": "ok", "service": "veritrack-api"}
