import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CompanyLeave(Base):
    """One leave day in the company leave register. Every GETS 'Out Of Office' day needs a matching row here;
    unique per manager/employee/day so re-uploads are idempotent."""

    __tablename__ = "company_leaves"
    __table_args__ = (
        UniqueConstraint("manager_id", "employee_code", "leave_date",
                         name="uq_company_leaves_manager_code_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    manager_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    employee_code: Mapped[str] = mapped_column(Text, nullable=False)
    leave_date: Mapped[date] = mapped_column(Date, nullable=False)
    leave_type: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'MANUAL'"))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("upload_batches.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "employee_code": self.employee_code,
            "leave_date": self.leave_date.isoformat(),
            "leave_type": self.leave_type,
            "source": self.source,
            "batch_id": str(self.batch_id) if self.batch_id else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
