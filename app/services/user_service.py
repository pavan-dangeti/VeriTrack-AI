"""User management service.

Role-creation authority and HR scoping are implemented HERE (service/query
layer), not sprinkled through routers, so every caller gets identical rules.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_initial_password, hash_password
from app.models.user import AuthType, User, UserRole
from app.services import audit_service


class UserRuleError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def assert_can_create(creator: User, target_role: UserRole) -> None:
    """Permission matrix: who may create which role."""
    if creator.role is UserRole.MASTER_ADMIN:
        if target_role not in (UserRole.MANAGER, UserRole.EXECUTIVE):
            raise UserRuleError(
                403,
                "forbidden_creation",
                "Master Admin may only create Managers and Executives",
            )
    elif creator.role is UserRole.MANAGER:
        if target_role is not UserRole.HR:
            raise UserRuleError(
                403, "forbidden_creation", "Managers may only create HR users"
            )
    else:
        raise UserRuleError(403, "forbidden_creation", "This role cannot create users")


async def create_user(
    db: AsyncSession,
    *,
    creator: User,
    email: str,
    role: UserRole,
) -> tuple[User, str]:
    assert_can_create(creator, role)

    normalized_email = email.strip().lower()
    existing = await get_by_email(db, normalized_email)
    if existing is not None:
        raise UserRuleError(409, "email_taken", "A user with this email already exists")

    initial_password = generate_initial_password()
    user = User(
        email=normalized_email,
        role=role,
        auth_type=AuthType.PASSWORD,
        password_hash=hash_password(initial_password),
        created_by=creator.id,
        manager_id=(
            creator.id if creator.role is UserRole.MANAGER and role is UserRole.HR else None
        ),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    await audit_service.record(
        db,
        action=audit_service.ACTION_CREATE_USER,
        result=audit_service.AuditResult.SUCCESS,
        actor_user_id=creator.id,
        target_entity="user",
        target_id=str(user.id),
        metadata={"role": role.value, "email_domain": normalized_email.split("@")[-1]},
    )
    return user, initial_password


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email.strip().lower())
    return (await db.execute(stmt)).scalar_one_or_none()


def scoped_users_query(actor: User):
    """Query-layer visibility scoping (permission matrix 'View all data').

    - MASTER_ADMIN / EXECUTIVE: every user
    - MANAGER: only the HR users they created (manager_id == actor.id)
    - HR: no listing rights (router rejects before reaching here)
    One implementation; every list endpoint must go through this.
    """
    if actor.role in (UserRole.MASTER_ADMIN, UserRole.EXECUTIVE):
        return select(User)
    return select(User).where(User.manager_id == actor.id)


async def list_users_scoped(
    db: AsyncSession, actor: User
) -> tuple[list[User], int]:
    base = scoped_users_query(actor)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    items = (
        (await db.execute(base.order_by(User.created_at.desc())))
        .scalars()
        .all()
    )
    return list(items), int(total)


async def set_active(
    db: AsyncSession, *, actor: User, target_id: uuid.UUID, is_active: bool
) -> User:
    """Enable/disable an account. Master Admin only (enforced by router dep).

    Guards: no self-disable; the Master Admin account can never be disabled —
    combined with the DB partial unique index this keeps exactly one active MA.
    """
    target = await db.get(User, target_id)
    if target is None:
        raise UserRuleError(404, "not_found", "User not found")
    if not is_active:
        if target.id == actor.id:
            raise UserRuleError(400, "self_disable", "You cannot disable your own account")
        if target.role is UserRole.MASTER_ADMIN:
            raise UserRuleError(
                400, "protected_account", "The Master Admin account cannot be disabled"
            )
    target.is_active = is_active
    await db.commit()

    await audit_service.record(
        db,
        action=(
            audit_service.ACTION_ENABLE_USER
            if is_active
            else audit_service.ACTION_DISABLE_USER
        ),
        result=audit_service.AuditResult.SUCCESS,
        actor_user_id=actor.id,
        target_entity="user",
        target_id=str(target.id),
        metadata={"role": target.role.value},
    )
    return target
