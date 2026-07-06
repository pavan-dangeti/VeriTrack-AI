from fastapi import APIRouter
from fastapi import Depends

from app.auth.permissions import require_permission

from app.models.user import User

from app.services.search_service import global_search

router = APIRouter(

    prefix="/search",

    tags=["Global Search"]

)


@router.get("/")
def search(

    q: str,

    current_user: User = Depends(

        require_permission(
            "can_view_reports"
        )

    )

):

    return global_search(q)