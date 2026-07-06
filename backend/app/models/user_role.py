from sqlalchemy import Column
from sqlalchemy import String
from sqlalchemy import Boolean
from sqlalchemy.dialects.postgresql import UUID

from app.db.database import Base

import uuid


class UserRole(Base):

    __tablename__ = "user_roles"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    role_name = Column(
        String,
        unique=True
    )

    can_upload = Column(Boolean)
    can_download = Column(Boolean)
    can_view_reports = Column(Boolean)
    can_generate_reports = Column(Boolean)
    can_receive_email = Column(Boolean)
    can_manage_users = Column(Boolean)

    can_upload_employee = Column(
        Boolean,
        default=False
    )

    can_upload_gets = Column(
        Boolean,
        default=False
    )

    can_compare = Column(
        Boolean,
        default=False
    )

    can_download_reports = Column(
        Boolean,
        default=False
    )

    can_create_roles = Column(
        Boolean,
        default=False
    )

    can_assign_manager = Column(
        Boolean,
        default=False
    )

    can_approve_requests = Column(
        Boolean,
        default=False
    )