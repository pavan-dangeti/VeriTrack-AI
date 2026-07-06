from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from app.schemas.master_admin import CreateManagerRequest

from app.auth.permissions import require_permission
from app.models.user import User

from app.db.database import SessionLocal

from app.auth.security import hash_password

from app.services.audit_service import log_action
from app.schemas.master_admin import (
    CreateManagerRequest,
    CreateHRRequest
)
from app.schemas.master_admin import (
    CreateManagerRequest,
    CreateHRRequest,
    AssignHRRequest
)

router = APIRouter(
    prefix="/master-admin",
    tags=["Master Admin"]
)


@router.post("/create-manager")
def create_manager(
    data: CreateManagerRequest,
    current_user: User = Depends(
        require_permission("can_manage_users")
    )
):

    if current_user.role != "MASTER_ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Only Master Admin can create managers"
        )

    db = SessionLocal()

    existing = db.query(User).filter(
        User.email == data.email
    ).first()

    if existing:
        db.close()
        raise HTTPException(
            status_code=400,
            detail="Manager already exists"
        )

    manager = User(
        name=data.name,
        email=data.email,
        password_hash=hash_password(data.password),
        role="MANAGER",
        approval_status="APPROVED",
        active=True
    )

    db.add(manager)
    db.commit()
    db.refresh(manager)

    log_action(
        current_user.email,
        "CREATE_MANAGER",
        manager.email
    )

    db.close()

    return {
        "message": "Manager created successfully",
        "manager_id": str(manager.id)
    }

@router.post("/create-hr")
def create_hr(
    data: CreateHRRequest,
    current_user: User = Depends(
        require_permission("can_manage_users")
    )
):

    if current_user.role != "MASTER_ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Only Master Admin can create HR"
        )

    db = SessionLocal()

    existing = db.query(User).filter(
        User.email == data.email
    ).first()

    if existing:
        db.close()
        raise HTTPException(
            status_code=400,
            detail="HR already exists"
        )

    hr = User(
        name=data.name,
        email=data.email,
        password_hash=hash_password(data.password),
        role="HR",
        approval_status="APPROVED",
        active=True
    )

    db.add(hr)
    db.commit()
    db.refresh(hr)

    log_action(
        current_user.email,
        "CREATE_HR",
        hr.email
    )

    db.close()

    return {
        "message": "HR created successfully",
        "hr_id": str(hr.id)
    }

@router.post("/assign-hr")
def assign_hr(
    data: AssignHRRequest,
    current_user: User = Depends(
        require_permission("can_manage_users")
    )
):

    if current_user.role != "MASTER_ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Only Master Admin can assign HR"
        )

    db = SessionLocal()

    manager = db.query(User).filter(
        User.id == data.manager_id,
        User.role == "MANAGER"
    ).first()

    if manager is None:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Manager not found"
        )

    hr = db.query(User).filter(
        User.id == data.hr_id,
        User.role == "HR"
    ).first()

    if hr is None:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="HR not found"
        )

    hr.manager_id = str(manager.id)

    db.commit()

    log_action(
        current_user.email,
        "ASSIGN_HR",
        f"{hr.email} -> {manager.email}"
    )

    db.refresh(hr)

    db.close()

    return {
        "message": "HR assigned successfully",
        "manager": manager.email,
        "hr": hr.email
    }