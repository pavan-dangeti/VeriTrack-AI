from sqlalchemy import Column
from sqlalchemy import String
from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID

from app.db.database import Base

import uuid
from datetime import datetime


class Employee(Base):

    __tablename__ = "employees"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    employee_id = Column(
        String,
        unique=True
    )

    full_name = Column(String)

    company_email = Column(String)

    personal_email = Column(String)

    department = Column(String)

    customer = Column(String)

    manager = Column(String)

    # NEW
    manager_id = Column(
        String,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )