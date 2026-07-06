from fastapi import APIRouter
from fastapi import Depends

from app.auth.permissions import require_permission

from app.models.user import User

from app.services.analytics_service import get_analytics

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"]
)


@router.get("/")
def analytics(

    current_user: User = Depends(
        require_permission(
            "can_view_reports"
        )
    )

):

    return get_analytics()