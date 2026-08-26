import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserCreate(BaseModel):
    model_config = {"str_strip_whitespace": True}
    email: EmailStr = Field(max_length=320)
    role: UserRole


class UserStatusUpdate(BaseModel):
    is_active: bool


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    role: UserRole
    email: str
    auth_type: str
    is_active: bool
    manager_id: uuid.UUID | None
    created_at: datetime | None
    last_login_at: datetime | None


class UserCreatedOut(BaseModel):
    """The initial password is returned exactly once, to the creating admin."""

    user: UserOut
    initial_password: str


class UserListOut(BaseModel):
    items: list[UserOut]
    total: int
