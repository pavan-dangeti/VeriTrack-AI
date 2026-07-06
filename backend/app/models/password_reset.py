from sqlalchemy import Column
from sqlalchemy import String
from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID

from app.db.database import Base

import uuid
from datetime import datetime


class PasswordReset(Base):

    __tablename__ = "password_resets"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    email = Column(
        String,
        nullable=False
    )

    token = Column(
        String,
        unique=True,
        nullable=False
    )

    expires_at = Column(
        DateTime,
        nullable=False
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )