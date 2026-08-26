"""User management routes — RBAC-protected endpoints.

Creation authority (permission matrix):
- MASTER_ADMIN creates MANAGER / EXECUTIVE
- MANAGER creates HR (manager_id forced to the creator)
Listing is scoped at the query layer via user_service.list_users_scoped.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import DB, require_role
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserCreatedOut, UserListOut, UserOut, UserStatusUpdate
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])

Creator = Annotated[
    User,
    Depends(require_role(UserRole.MASTER_ADMIN, UserRole.MANAGER)),
]
Viewer = Annotated[
    User,
    Depends(require_role(UserRole.MASTER_ADMIN, UserRole.EXECUTIVE, UserRole.MANAGER)),
]
MasterAdminOnly = Annotated[User, Depends(require_role(UserRole.MASTER_ADMIN))]


@router.post("", response_model=UserCreatedOut, status_code=201)
async def create_user(body: UserCreate, actor: Creator, db: DB):
    try:
        user, initial_password = await user_service.create_user(
            db, creator=actor, email=body.email, role=body.role
        )
    except user_service.UserRuleError as exc:
        raise HTTPException(
            exc.status_code, detail={"code": exc.code, "message": exc.message}
        ) from exc
    return UserCreatedOut(
        user=UserOut.model_validate(user), initial_password=initial_password
    )


@router.get("", response_model=UserListOut)
async def list_users(actor: Viewer, db: DB):
    items, total = await user_service.list_users_scoped(db, actor)
    return UserListOut(items=[UserOut.model_validate(u) for u in items], total=total)


@router.patch("/{user_id}/status", response_model=UserOut)
async def set_user_status(
    user_id: uuid.UUID,
    body: UserStatusUpdate,
    actor: MasterAdminOnly,
    db: DB,
):
    try:
        target = await user_service.set_active(
            db, actor=actor, target_id=user_id, is_active=body.is_active
        )
    except user_service.UserRuleError as exc:
        raise HTTPException(
            exc.status_code, detail={"code": exc.code, "message": exc.message}
        ) from exc
    return UserOut.model_validate(target)
