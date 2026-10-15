"""Durable audit trail writer. Each entry commits independently so it survives a later request failure."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.tenant import SYSTEM, current
from app.models.audit_log import AuditLog, AuditResult

log = get_logger("audit")

ACTION_LOGIN = "LOGIN_PASSWORD"
ACTION_LOGIN_M365 = "LOGIN_M365"
ACTION_LOGOUT = "LOGOUT"
ACTION_REFRESH = "REFRESH"
ACTION_REFRESH_REUSE = "REFRESH_TOKEN_REUSE"
ACTION_CREATE_USER = "CREATE_USER"
ACTION_ENABLE_USER = "ENABLE_USER"
ACTION_DISABLE_USER = "DISABLE_USER"
ACTION_RBAC_DENIED = "RBAC_DENIED"
ACTION_BOOTSTRAP_ADMIN = "BOOTSTRAP_MASTER_ADMIN"
ACTION_ADMIN_CREDENTIALS_SYNCED = "ADMIN_CREDENTIALS_SYNCED"
ACTION_DEMO_RESET = "DEMO_RESET"
ACTION_DEMO_ACCOUNT_CREATED = "DEMO_ACCOUNT_CREATED"
ACTION_AUDIT_VERIFIED = "AUDIT_LOG_VERIFIED"


async def record(
    db: AsyncSession,
    *,
    action: str,
    result: AuditResult,
    actor_user_id: uuid.UUID | None = None,
    target_entity: str | None = None,
    target_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    entry = AuditLog(
        actor_user_id=actor_user_id,
        action=action[:100],
        target_entity=target_entity[:100] if target_entity else None,
        target_id=str(target_id)[:100] if target_id else None,
        ip_address=ip_address,
        user_agent=user_agent,
        result=result,
        event_metadata=metadata,
    )
    if current() == SYSTEM and actor_user_id is not None:
        # sign-in and CLI steps run before an organisation is set: the entry belongs to the actor's
        from app.models.user import User

        entry.org_id = select(User.org_id).where(User.id == actor_user_id).scalar_subquery()
    db.add(entry)
    await db.commit()
    log.info(
        "audit",
        action=action,
        result=result.value,
        actor=str(actor_user_id) if actor_user_id else None,
        target_entity=target_entity,
        target_id=target_id,
    )
