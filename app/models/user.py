import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserRole(enum.StrEnum):
    MASTER_ADMIN = "MASTER_ADMIN"
    EXECUTIVE = "EXECUTIVE"
    MANAGER = "MANAGER"
    HR = "HR"


class AuthType(enum.StrEnum):  # noqa: S105 - role labels, not secrets
    M365 = "M365"
    PASSWORD = "PASSWORD"  # noqa: S105 - auth-type label, not a secret


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=True), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    auth_type: Mapped[AuthType] = mapped_column(
        Enum(AuthType, name="auth_type", native_enum=True), nullable=False
    )
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", use_alter=True, name="fk_users_manager_id"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", use_alter=True, name="fk_users_created_by"),
        nullable=True,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Account lockout state (5 failures within window => locked for a duration)
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    manager: Mapped[User | None] = relationship(
        "User", remote_side=[id], foreign_keys=[manager_id], lazy="selectin"
    )

    def public_dict(self) -> dict:
        return {
            "id": str(self.id),
            "role": self.role.value,
            "email": self.email,
            "auth_type": self.auth_type.value,
            "is_active": self.is_active,
            "manager_id": str(self.manager_id) if self.manager_id else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }
