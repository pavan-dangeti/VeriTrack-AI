import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Employee(Base):
    """Per-manager employee master record. Never destructively edited:
    every change inserts a new row in employee_versions."""

    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("manager_id", "employee_code", name="uq_employees_manager_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    manager_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    employee_code: Mapped[str] = mapped_column(Text, nullable=False)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        # circular FK to employee_versions.id; use_alter breaks creation order
        ForeignKey("employee_versions.id", ondelete="SET NULL", use_alter=True,
                   name="fk_employees_current_version"),
        nullable=True,
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    versions: Mapped[list[EmployeeVersion]] = relationship(
        back_populates="employee",
        cascade="all, delete-orphan",
        foreign_keys="EmployeeVersion.employee_id",
        order_by="EmployeeVersion.version_no.desc()",
    )
    current_version: Mapped[EmployeeVersion | None] = relationship(
        foreign_keys=[current_version_id], lazy="selectin"
    )


class EmployeeVersion(Base):
    __tablename__ = "employee_versions"
    __table_args__ = (
        UniqueConstraint("employee_id", "version_no", name="uq_employee_versions_no"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        index=True,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    official_email: Mapped[str | None] = mapped_column(Text)
    personal_email: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # UPLOAD = bulk import; CORRECTION = manual inline edit via API
    change_source: Mapped[str] = mapped_column(Text, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    employee: Mapped[Employee] = relationship(
        back_populates="versions", foreign_keys=[employee_id]
    )

    def public_dict(self) -> dict:
        return {
            "employee_id": str(self.employee_id),
            "version": self.version_no,
            "full_name": self.full_name,
            "official_email": self.official_email,
            "personal_email": self.personal_email,
            "department": self.department,
            "change_source": self.change_source,
            "changed_by": str(self.changed_by) if self.changed_by else None,
            "created_at": self.created_at.isoformat(),
        }
