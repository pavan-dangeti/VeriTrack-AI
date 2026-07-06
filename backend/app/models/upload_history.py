from sqlalchemy import Column
from sqlalchemy import String
from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID

from app.db.database import Base

import uuid
from datetime import datetime


class UploadHistory(Base):

    __tablename__ = "upload_history"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    filename = Column(
        String,
        nullable=False
    )

    # SHA-256 Hash of uploaded file
    file_hash = Column(
        String,
        unique=True,
        nullable=True
    )

    category = Column(
        String,
        nullable=False
    )

    status = Column(
        String,
        nullable=False
    )

    uploaded_by = Column(
        String,
        nullable=False
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )