from fastapi import APIRouter
from fastapi import Depends

from app.auth.dependencies import get_current_user
from app.db.database import SessionLocal

from app.models.user import User
from app.models.upload_history import UploadHistory

router = APIRouter(
    prefix="/upload-history",
    tags=["Upload History"]
)


@router.get("/")
def get_upload_history(
    current_user: User = Depends(get_current_user)
):

    db = SessionLocal()

    if current_user.role == "MASTER_ADMIN":

        uploads = (
            db.query(UploadHistory)
            .order_by(UploadHistory.created_at.desc())
            .all()
        )

    elif current_user.role == "MANAGER":

        uploads = (
            db.query(UploadHistory)
            .filter(
                UploadHistory.uploaded_by == current_user.email
            )
            .order_by(UploadHistory.created_at.desc())
            .all()
        )

    elif current_user.role == "HR":

        manager = (
            db.query(User)
            .filter(User.id == current_user.manager_id)
            .first()
        )

        uploads = (
            db.query(UploadHistory)
            .filter(
                UploadHistory.uploaded_by == manager.email
            )
            .order_by(UploadHistory.created_at.desc())
            .all()
        )

    else:

        uploads = []

    db.close()

    return uploads