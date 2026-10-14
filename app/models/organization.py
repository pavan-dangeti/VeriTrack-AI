import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.db.base import Base

# org_id is filled by the database from the transaction's tenant setting (see app/db/tenant.py); with no tenant
# set it is NULL and NOT NULL refuses the insert
TENANT_DEFAULT = text("nullif(current_setting('app.org_id', true), '')::uuid")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TenantScoped:
    """Rows of this table belong to one organisation. Row-level security restricts every query and write to
    the current tenant (migration 0008, app/db/tenant.py)."""

    __mapper_args__ = {"eager_defaults": True}

    @declared_attr
    def org_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(PGUUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True,
                             server_default=TENANT_DEFAULT)
