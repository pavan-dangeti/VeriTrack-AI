from sqlalchemy import Column
from sqlalchemy import String
from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

import uuid

from app.db.database import Base


class ReportHistory(Base):

    __tablename__ = "report_history"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    manager_id = Column(
        String,
        nullable=False
    )

    manager_email = Column(
        String,
        nullable=False
    )

    filename = Column(
        String,
        nullable=False
    )

    report_path = Column(
        String,
        nullable=False
    )

    report_type = Column(
        String,
        default="Compliance Report"
    )

    generated_at = Column(
        DateTime,
        server_default=func.now()
    )

    downloaded_by = Column(
        String,
        nullable=True
    )

    downloaded_at = Column(
        DateTime,
        nullable=True
    )