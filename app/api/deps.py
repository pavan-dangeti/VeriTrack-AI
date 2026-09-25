"""Shared FastAPI dependencies: DB session, current user, role checks, CSRF."""

import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt as pyjwt
import sqlalchemy.exc
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission, role_has
from app.core.security import constant_time_equals, decode_token
from app.db.session import get_db
from app.models.user import User
from app.services import audit_service
from app.services.auth_service import AuthError, get_user_by_email

bearer_scheme = HTTPBearer(auto_error=False)

DB = Annotated[AsyncSession, Depends(get_db)]


@dataclass(frozen=True)
class RequestContext:
    ip_address: str | None
    user_agent: str | None


def get_request_context(request: Request) -> RequestContext:
    # uvicorn runs with --proxy-headers, so request.client is already the
    # real client address behind a trusted load balancer (a valid INET)
    ip = request.client.host if request.client else None
    return RequestContext(ip_address=ip, user_agent=request.headers.get("user-agent"))


Ctx = Annotated[RequestContext, Depends(get_request_context)]


async def get_current_user(
    db: DB,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """Loads the user from a validated access token; the role always comes from the DB, never the client."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "unauthorized", "message": "Authentication required"},
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized
    try:
        payload = decode_token(credentials.credentials, "access")
    except pyjwt.PyJWTError as exc:
        raise unauthorized from exc

    try:
        user = await db.get(User, uuid.UUID(payload["sub"]))
    except (ValueError, sqlalchemy.exc.DataError) as exc:
        raise unauthorized from exc
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def _require_roles_factory(allowed_roles, permission_for_audit: Permission | None):
    async def dependency(user: CurrentUser, ctx: Ctx, db: DB) -> User:
        if user.role in allowed_roles:
            return user
        if permission_for_audit is not None and not role_has(user.role, permission_for_audit):
            pass  # logged below regardless of map state
        await audit_service.record(
            db,
            action=audit_service.ACTION_RBAC_DENIED,
            result=audit_service.AuditResult.DENIED,
            actor_user_id=user.id,
            target_entity="endpoint",
            metadata={
                "required_roles": [r.value for r in allowed_roles],
                "actor_role": user.role.value,
                "permission": permission_for_audit.value if permission_for_audit else None,
            },
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden", "message": "Insufficient permissions"},
        )

    return dependency


def require_role(*allowed_roles, audit_permission: Permission | None = None):
    """Per-endpoint RBAC gate; every denial is written to the audit log."""
    return _require_roles_factory(set(allowed_roles), audit_permission)


async def verify_csrf(
    request: Request,
    x_csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    """Double-submit cookie check for endpoints that read the refresh cookie."""
    cookie_token = request.cookies.get("veritrack_csrf", "")
    if not cookie_token or not x_csrf_token or not constant_time_equals(cookie_token, x_csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "csrf_failed", "message": "CSRF token missing or invalid"},
        )


__all__ = [
    "AuthError",
    "CurrentUser",
    "DB",
    "Ctx",
    "RequestContext",
    "get_current_user",
    "get_request_context",
    "get_user_by_email",
    "require_role",
    "verify_csrf",
]
