from sqlalchemy import Column
from sqlalchemy import String
from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID

from app.db.database import Base

import uuid
from datetime import datetime


class UserRequest(Base):

    __tablename__ = "user_requests"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    name = Column(String)

    email = Column(String)

    requested_role = Column(String)

    reason = Column(String)

    status = Column(
        String,
        default="PENDING"
    )

    approved_by = Column(
        String,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )