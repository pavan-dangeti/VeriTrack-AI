import uuid
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.audit_log import AuditResult


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_user_id: uuid.UUID | None
    action: str
    target_entity: str | None
    target_id: str | None
    ip_address: str | None
    user_agent: str | None
    result: AuditResult
    timestamp: datetime
    event_metadata: dict[str, Any] | None = None

    @field_validator("ip_address", mode="before")
    @classmethod
    def _ip_to_str(cls, value):
        # Postgres INET arrives as IPv4Address/IPv6Address via asyncpg.
        return str(value) if isinstance(value, (IPv4Address, IPv6Address)) else value


class AuditLogPage(BaseModel):
    items: list[AuditLogOut]
    total: int
    limit: int
    offset: int
