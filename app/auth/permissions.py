from fastapi import Depends
from fastapi import HTTPException

from app.auth.dependencies import get_current_user
from app.db.database import SessionLocal
from app.models.user import User
from app.models.user_role import UserRole


def require_permission(permission: str):

    def permission_checker(
        current_user: User = Depends(get_current_user)
    ):

        # Hard business rule:
        # HR is always read-only.
        if (
            current_user.role == "HR"
            and permission in [
                "can_upload_employee",
                "can_upload_gets",
                "can_compare",
                "can_download_reports",
                "can_manage_users",
                "can_create_roles",
                "can_assign_manager",
                "can_approve_requests"
            ]
        ):
            raise HTTPException(
                status_code=403,
                detail="HR has read-only access."
            )

        db = SessionLocal()

        role = db.query(UserRole).filter(
            UserRole.role_name == current_user.role
        ).first()

        db.close()

        if role is None:
            raise HTTPException(
                status_code=403,
                detail="Role not found"
            )

        if not getattr(role, permission, False):
            raise HTTPException(
                status_code=403,
                detail="Permission denied"
            )

        return current_user

    return permission_checker