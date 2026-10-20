import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    FetchedValue,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.organization import TENANT_DEFAULT


class AuditResult(enum.StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"


class AuditLog(Base):
    # Indexes (actor_user_id, timestamp DESC, action) are created explicitly
    # in alembic/versions/0001_foundation.py.
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # nullable: a failed sign-in for an unknown e-mail belongs to no organisation
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True, index=True,
        server_default=TENANT_DEFAULT,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_entity: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[AuditResult] = mapped_column(
        Enum(AuditResult, name="audit_result", native_enum=True), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Column is named `metadata` in the DB (per spec); Python attr avoids the
    # declarative `metadata` name clash.
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    # the hash chain, written by a trigger on insert (migration 0009); never set by the application
    chain_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=FetchedValue())
    prev_hash: Mapped[str] = mapped_column(Text, nullable=False, server_default=FetchedValue())
    entry_hash: Mapped[str] = mapped_column(Text, nullable=False, server_default=FetchedValue())
