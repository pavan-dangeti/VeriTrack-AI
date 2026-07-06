from fastapi import APIRouter, Depends, HTTPException

from app.auth.permissions import require_permission
from app.models.user import User
from app.db.database import SessionLocal

router = APIRouter(
    prefix="/manager",
    tags=["Manager"]
)


@router.put("/assign")
def assign_hr_to_manager(
    hr_email: str,
    manager_email: str,
    current_user: User = Depends(
        require_permission("can_assign_manager")
    )
):

    db = SessionLocal()

    hr = db.query(User).filter(
        User.email == hr_email
    ).first()

    manager = db.query(User).filter(
        User.email == manager_email
    ).first()

    if hr is None:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="HR user not found"
        )

    if manager is None:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Manager not found"
        )

    hr.manager_id = str(manager.id)

    db.commit()
    db.refresh(hr)

    db.close()

    return {
        "message": "HR assigned successfully",
        "hr": hr.email,
        "manager": manager.email
    }