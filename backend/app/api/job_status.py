from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from app.auth.permissions import require_permission
from app.models.user import User

from app.db.database import SessionLocal
from app.models.upload_history import UploadHistory

router = APIRouter(
    prefix="/jobs",
    tags=["Job Status"]
)


@router.get("/{filename}")
def get_job_status(
    filename: str,
    current_user: User = Depends(
        require_permission("can_upload_gets")
    )
):

    db = SessionLocal()

    upload = (
        db.query(UploadHistory)
        .filter(
            UploadHistory.filename == filename
        )
        .first()
    )

    db.close()

    if upload is None:

        raise HTTPException(
            status_code=404,
            detail="Job not found."
        )

    return {

        "filename": upload.filename,

        "status": upload.status,

        "uploaded_by": upload.uploaded_by,

        "uploaded_at": upload.created_at

    }