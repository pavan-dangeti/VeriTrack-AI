import uuid
from fastapi import APIRouter, Depends, HTTPException

from app.schemas.role import RoleCreate, RoleUpdate
from app.models.user_role import UserRole
from app.db.database import SessionLocal

from app.auth.permissions import require_permission
from app.models.user import User

router = APIRouter(
    prefix="/roles",
    tags=["Role Management"]
)


@router.post("/")
def create_role(
    data: RoleCreate,
    current_user: User = Depends(
        require_permission("can_create_roles")
    )
):

    db = SessionLocal()

    existing = db.query(UserRole).filter(
        UserRole.role_name == data.role_name
    ).first()

    if existing:
        db.close()
        raise HTTPException(
            status_code=400,
            detail="Role already exists"
        )

    role = UserRole(**data.model_dump())

    db.add(role)
    db.commit()
    db.refresh(role)

    db.close()

    return role


@router.get("/")
def get_roles(
    current_user: User = Depends(
        require_permission("can_manage_users")
    )
):

    db = SessionLocal()

    roles = db.query(UserRole).all()

    db.close()

    return roles


@router.get("/{role_id}")
def get_role(
    role_id: str,
    current_user: User = Depends(
        require_permission("can_manage_users")
    )
):

    db = SessionLocal()

    role = db.query(UserRole).filter(
    UserRole.id == uuid.UUID(role_id)
).first()

    db.close()

    if not role:
        raise HTTPException(
            status_code=404,
            detail="Role not found"
        )

    return role


@router.put("/{role_id}")
def update_role(
    role_id: str,
    data: RoleUpdate,
    current_user: User = Depends(
        require_permission("can_create_roles")
    )
):

    db = SessionLocal()

    role = db.query(UserRole).filter(
    UserRole.id == uuid.UUID(role_id)
).first()

    if not role:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Role not found"
        )

    for key, value in data.model_dump().items():
        setattr(role, key, value)

    db.commit()
    db.refresh(role)

    db.close()

    return role


@router.delete("/{role_id}")
def delete_role(
    role_id: str,
    current_user: User = Depends(
        require_permission("can_create_roles")
    )
):

    db = SessionLocal()

    role = db.query(UserRole).filter(
    UserRole.id == uuid.UUID(role_id)
).first()

    if not role:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Role not found"
        )

    db.delete(role)
    db.commit()
    db.close()

    return {
        "message": "Role deleted successfully"
    }