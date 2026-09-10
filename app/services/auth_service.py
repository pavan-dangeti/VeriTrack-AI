"""Authentication service: password login with lockout, JWT issuance,
refresh token rotation with reuse detection."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import AuthType, User
from app.services import audit_service

log = get_logger("auth")


class AuthError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    refresh_jti: str

    @property
    def expires_in(self) -> int:
        return settings.access_token_expire_minutes * 60


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email.strip().lower())
    return (await db.execute(stmt)).scalar_one_or_none()


def _issue_pair(db: AsyncSession, user: User) -> TokenPair:
    access, _ = create_access_token(user_id=user.id, role=user.role.value)
    refresh, refresh_jti = create_refresh_token(user_id=user.id)
    db.add(
        RefreshToken(
            user_id=user.id,
            jti=refresh_jti,
            token_hash=hash_refresh_token(refresh),
            expires_at=datetime.now(UTC)
            + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    return TokenPair(access_token=access, refresh_token=refresh, refresh_jti=refresh_jti)


async def authenticate_password(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, TokenPair]:
    """Validates credentials; enforces lockout; writes an audit entry for every attempt.

    Unknown-email and wrong-password both raise the same generic error so the
    endpoint cannot be used to enumerate accounts.
    """
    now = datetime.now(UTC)
    user = await get_user_by_email(db, email)

    if user is None:
        # Burn comparable CPU time to blunt timing-based user enumeration.
        hash_password("timing-equalizer-dummy-password")
        await audit_service.record(
            db,
            action=audit_service.ACTION_LOGIN,
            result=audit_service.AuditResult.FAILURE,
            target_entity="user",
            target_id=email.lower(),
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "unknown_email"},
        )
        raise AuthError(401, "invalid_credentials", "Invalid email or password")

    if not user.is_active:
        await audit_service.record(
            db,
            action=audit_service.ACTION_LOGIN,
            result=audit_service.AuditResult.DENIED,
            actor_user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "account_disabled"},
        )
        raise AuthError(401, "invalid_credentials", "Invalid email or password")

    # Verify FIRST: a correct password always authenticates, even while locked,
    # so an attacker can neither DoS the owner out of their account nor detect
    # lockout state (there is no lockout-specific response anymore).
    password_ok = user.auth_type is AuthType.PASSWORD and verify_password(
        password, user.password_hash or ""
    )

    if not password_ok:
        locked_now = user.locked_until is not None and user.locked_until > now
        if not locked_now:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.lockout_threshold:
                user.locked_until = now + timedelta(
                    minutes=settings.lockout_duration_minutes
                )
                user.failed_login_attempts = 0  # lockout clock governs now
                locked_now = True
        await db.commit()
        await audit_service.record(
            db,
            action=audit_service.ACTION_LOGIN,
            result=audit_service.AuditResult.FAILURE,
            actor_user_id=user.id,
            target_entity="user",
            target_id=str(user.id),
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "bad_password", "locked": locked_now},
        )
        # Same response as every other failure — no enumeration oracle.
        raise AuthError(401, "invalid_credentials", "Invalid email or password")

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    await db.commit()

    pair = _issue_pair(db, user)
    await db.commit()
    await audit_service.record(
        db,
        action=audit_service.ACTION_LOGIN,
        result=audit_service.AuditResult.SUCCESS,
        actor_user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return user, pair


async def revoke_all_for_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


async def rotate_refresh(
    db: AsyncSession,
    *,
    raw_refresh_token: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, TokenPair]:
    try:
        payload = decode_token(raw_refresh_token, "refresh")
    except pyjwt.PyJWTError as exc:
        raise AuthError(401, "invalid_refresh", "Invalid refresh token") from exc

    jti = payload["jti"]
    row = (
        await db.execute(select(RefreshToken).where(RefreshToken.jti == jti))
    ).scalar_one_or_none()

    if row is None:
        await audit_service.record(
            db,
            action=audit_service.ACTION_REFRESH,
            result=audit_service.AuditResult.DENIED,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "unknown_jti"},
        )
        raise AuthError(401, "invalid_refresh", "Invalid refresh token")

    now = datetime.now(UTC)

    if row.revoked_at is not None:
        # Reuse of a rotated token => assume theft. Kill every session for this user.
        await revoke_all_for_user(db, row.user_id)
        await audit_service.record(
            db,
            action=audit_service.ACTION_REFRESH_REUSE,
            result=audit_service.AuditResult.DENIED,
            actor_user_id=row.user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"jti": jti},
        )
        log.warning("refresh_token_reuse_detected", user_id=str(row.user_id), jti=jti)
        raise AuthError(401, "token_reuse_detected", "Session revoked. Please log in again.")

    if hash_refresh_token(raw_refresh_token) != row.token_hash:
        await revoke_all_for_user(db, row.user_id)
        await audit_service.record(
            db,
            action=audit_service.ACTION_REFRESH_REUSE,
            result=audit_service.AuditResult.DENIED,
            actor_user_id=row.user_id,
            ip_address=ip_address,
            metadata={"reason": "hash_mismatch"},
        )
        raise AuthError(401, "invalid_refresh", "Invalid refresh token")

    if row.expires_at < now:
        raise AuthError(401, "expired_refresh", "Refresh token expired")

    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AuthError(401, "invalid_refresh", "Account unavailable")

    new_raw, new_jti = create_refresh_token(user_id=row.user_id)
    row.revoked_at = now
    row.replaced_by_jti = uuid.UUID(new_jti)
    db.add(
        RefreshToken(
            user_id=row.user_id,
            jti=new_jti,
            token_hash=hash_refresh_token(new_raw),
            expires_at=now + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    access, _ = create_access_token(user_id=user.id, role=user.role.value)
    await db.commit()
    return user, TokenPair(access_token=access, refresh_token=new_raw, refresh_jti=new_jti)


async def revoke_by_raw_token(db: AsyncSession, raw_refresh_token: str | None) -> None:
    """Logout: revoke the presented token if it is a valid, unrevoked one."""
    if not raw_refresh_token:
        return
    try:
        payload = decode_token(raw_refresh_token, "refresh")
    except pyjwt.PyJWTError:
        return
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.jti == payload["jti"],
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()
