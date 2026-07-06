from fastapi import APIRouter
from fastapi import Depends

from app.auth.permissions import require_permission

from app.db.database import SessionLocal
from app.models.audit_log import AuditLog
from app.models.user import User

router = APIRouter(
    prefix="/audit",
    tags=["Audit Logs"]
)


@router.get("/logs")
def get_logs(
    current_user: User = Depends(
        require_permission("can_manage_users")
    )
):

    db = SessionLocal()

    logs = (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .all()
    )

    db.close()

    return logs