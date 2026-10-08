"""Public demo details for the sign-in page: the shared demo login and the sample timesheets."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import settings
from app.services import demo_service

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("")
async def demo_info() -> dict:
    """The demo credentials are public by design: the account holds synthetic data only and is reset daily."""
    if not demo_service.enabled():
        return {"enabled": False}
    return {
        "enabled": True,
        "email": (settings.demo_email or "").strip().lower(),
        "password": settings.demo_password,
        "samples": list(demo_service.SAMPLE_SHEETS),
        "reset_hours": settings.demo_reset_hours,
    }


@router.get("/samples/{name}")
async def demo_sample(name: str) -> FileResponse:
    path = demo_service.sample_path(name)
    if path is None or not demo_service.enabled():
        raise HTTPException(404, detail={"code": "not_found", "message": "No such sample"})
    return FileResponse(path, media_type="image/png", filename=name)
