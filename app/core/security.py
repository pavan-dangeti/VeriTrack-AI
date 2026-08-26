"""Cryptographic utilities: password hashing, JWT creation/validation, token helpers."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings

TokenType = Literal["access", "refresh"]


# --- Passwords ---------------------------------------------------------------


def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    return bcrypt.hashpw(plain.encode(), salt).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def generate_initial_password() -> str:
    """16-char url-safe password handed to the creator exactly once."""
    return secrets.token_urlsafe(12)


# --- JWT ----------------------------------------------------------------------


def _create_token(
    *,
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    role: str | None = None,
) -> tuple[str, str]:
    """Returns (encoded_jwt, jti)."""
    now = datetime.now(UTC)
    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "jti": jti,
        "iat": now,
        "exp": now + expires_delta,
        "iss": "veritrack",
        "aud": "veritrack",
    }
    if role is not None:
        payload["role"] = role
    encoded = jwt.encode(
        payload, settings.jwt_secret_key or "", algorithm=settings.jwt_algorithm
    )
    return encoded, jti


def create_access_token(*, user_id: uuid.UUID, role: str) -> tuple[str, str]:
    return _create_token(
        subject=str(user_id),
        role=role,
        token_type="access",  # noqa: S106 - token class label, not a secret
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(*, user_id: uuid.UUID) -> tuple[str, str]:
    return _create_token(
        subject=str(user_id),
        token_type="refresh",  # noqa: S106 - token class label, not a secret
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Raises jwt.PyJWTError subtypes on any validation failure."""
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret_key or "",
        algorithms=[settings.jwt_algorithm],
        audience="veritrack",
        issuer="veritrack",
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected {expected_type} token")
    return payload


# --- Refresh token storage hash ------------------------------------------------


def hash_refresh_token(token: str) -> str:
    # The DB only stores a digest; a leaked dump cannot yield usable tokens.
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode(), b.encode())


# --- CSRF / state tokens --------------------------------------------------------


def new_state_token() -> str:
    return secrets.token_urlsafe(32)
