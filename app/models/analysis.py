import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AnalysisStatus(enum.StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EmailStatus(enum.StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    SKIPPED_NO_EMAIL = "SKIPPED_NO_EMAIL"
    ERROR = "ERROR"


class ReportKind(enum.StrEnum):
    SUMMARY_PDF = "SUMMARY_PDF"
    EXCEL_3TAB = "EXCEL_3TAB"


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("upload_batches.id", ondelete="CASCADE"),
        index=True,
        unique=True,
    )
    manager_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[AnalysisStatus] = mapped_column(
        Enum(AnalysisStatus, name="analysis_status"), nullable=False
    )
    files_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    matched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    violations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_missing: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_errored: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_rows: Mapped[list | None] = mapped_column(JSONB)  # [{code,status,reason}]
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    violations_list: Mapped[list["ViolationResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ViolationResult(Base):
    """One row per employee per analysis run. The UNIQUE(run_id, employee_code)
    constraint IS the dedup guarantee — one email per employee per run."""

    __tablename__ = "violation_results"
    __table_args__ = (
        UniqueConstraint("run_id", "employee_code", name="uq_violations_run_employee"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    manager_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    employee_code: Mapped[str] = mapped_column(Text, nullable=False)
    employee_name: Mapped[str | None] = mapped_column(Text)
    customer_leave_value: Mapped[str | None] = mapped_column(Text)
    sacha_leave_value: Mapped[str | None] = mapped_column(Text)
    violation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    # Email resolution snapshot at run time (Official -> Personal -> none)
    email_to: Mapped[str | None] = mapped_column(Text)
    email_status: Mapped[EmailStatus] = mapped_column(
        Enum(EmailStatus, name="email_status"), default=EmailStatus.PENDING, nullable=False
    )
    email_error: Mapped[str | None] = mapped_column(Text)
    graph_message_id: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped["AnalysisRun"] = relationship(back_populates="violations_list")


class GeneratedReport(Base):
    __tablename__ = "generated_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ReportKind] = mapped_column(Enum(ReportKind, name="report_kind"), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    emailed_to: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
