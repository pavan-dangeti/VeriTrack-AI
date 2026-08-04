from datetime import datetime
from datetime import timedelta

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request

from app.core.rate_limit import limiter
from app.core.logger import logger

from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshTokenRequest,
    LogoutRequest,
)

from app.auth.security import (
    verify_password,
    hash_password,
)

from app.auth.jwt import (
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
)

from app.db.database import SessionLocal
from app.models.user import User

from app.schemas.password_reset import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
)

from app.services.password_reset_service import (
    create_reset_token,
    get_reset_token,
    delete_reset_token,
)

from app.services.email_service import (
    send_password_reset_email,
)

from app.services.refresh_token_service import (
    save_refresh_token,
    get_refresh_token,
    revoke_refresh_token,
)

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

MAX_LOGIN_ATTEMPTS = 999999
LOCK_TIME_MINUTES = 0


# =====================================================
# LOGIN
# =====================================================

@router.post("/login", response_model=LoginResponse)
@limiter.limit("1000/minute")
def login(
    request: Request,
    data: LoginRequest,
):

    db = SessionLocal()

    user = (
        db.query(User)
        .filter(User.email == data.email)
        .first()
    )

    if user is None:

        db.close()

        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    # =====================================================
    # Account Lock Check
    # =====================================================

    if user.is_locked:

        if (
            user.locked_until is not None
            and user.locked_until > datetime.utcnow()
        ):

            db.close()

            raise HTTPException(
                status_code=423,
                detail="Account temporarily locked. Try again later.",
            )

        user.is_locked = False
        user.failed_login_attempts = 0
        user.locked_until = None

        db.commit()

    # =====================================================
    # Approval Check
    # =====================================================

    if user.approval_status != "APPROVED":

        db.close()

        logger.warning(
            f"Failed login: {data.email}"
        )

        raise HTTPException(
            status_code=403,
            detail="Your account is not approved.",
        )

    # =====================================================
    # Active Check
    # =====================================================

    if not user.active:

        db.close()

        logger.warning(
            f"Failed login: {data.email}"
        )

        raise HTTPException(
            status_code=403,
            detail="Your account has been disabled.",
        )

    # =====================================================
    # Password Verification
    # =====================================================

    if not verify_password(
        data.password,
        user.password_hash,
    ):

        user.failed_login_attempts += 1

        if user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:

            user.is_locked = True

            user.locked_until = (
                datetime.utcnow()
                + timedelta(minutes=LOCK_TIME_MINUTES)
            )

        db.commit()
        db.close()

        logger.warning(
            f"Failed login: {data.email}"
        )

        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    # =====================================================
    # Successful Login
    # =====================================================

    user.failed_login_attempts = 0
    user.is_locked = False
    user.locked_until = None

    db.commit()

    access_token = create_access_token(
        {
            "sub": user.email,
            "role": user.role,
            "manager_id": user.manager_id,
        }
    )

    refresh_token = create_refresh_token(
        {
            "sub": user.email,
            "role": user.role,
            "manager_id": user.manager_id,
        }
    )

    save_refresh_token(
        str(user.id),
        refresh_token,
    )

    db.close()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 900,
        "user": {
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "manager_id": user.manager_id,
        },
    }


# =====================================================
# REFRESH TOKEN
# =====================================================

@router.post("/refresh", response_model=LoginResponse)
def refresh(
    data: RefreshTokenRequest,
):

    payload = verify_refresh_token(
        data.refresh_token
    )

    if payload is None:

        logger.warning("Invalid refresh token.")

        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token",
        )

    token = get_refresh_token(
        data.refresh_token
    )

    if token is None:

        logger.warning("Refresh token has been revoked.")

        raise HTTPException(
            status_code=401,
            detail="Refresh token has been revoked.",
        )

    if token.expires_at < datetime.utcnow():

        revoke_refresh_token(
            data.refresh_token
        )

        raise HTTPException(
            status_code=401,
            detail="Refresh token expired.",
        )

    access_token = create_access_token(
        {
            "sub": payload["sub"],
            "role": payload.get("role"),
            "manager_id": payload.get("manager_id"),
        }
    )

    db = SessionLocal()

    user = (
        db.query(User)
        .filter(User.email == payload["sub"])
        .first()
    )

    db.close()

    if user is None:

        raise HTTPException(
            status_code=404,
            detail="User not found.",
        )

    return {
        "access_token": access_token,
        "refresh_token": data.refresh_token,
        "token_type": "bearer",
        "expires_in": 900,
        "user": {
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "manager_id": user.manager_id,
        },
    }


# =====================================================
# LOGOUT
# =====================================================

@router.post("/logout")
def logout(
    data: LogoutRequest,
):

    payload = verify_refresh_token(
        data.refresh_token
    )

    revoke_refresh_token(
        data.refresh_token
    )

    if payload:

        logger.info(
            f"User {payload['sub']} logged out successfully."
        )

    return {
        "message": "Logged out successfully."
    }


# =====================================================
# FORGOT PASSWORD
# =====================================================

@router.post("/forgot-password")
def forgot_password(
    data: ForgotPasswordRequest,
):

    db = SessionLocal()

    user = (
        db.query(User)
        .filter(User.email == data.email)
        .first()
    )

    if user:

        token = create_reset_token(
            user.email
        )

        send_password_reset_email(
            user.email,
            token,
        )

        logger.info(
            f"Password reset requested: {user.email}"
        )

    db.close()

    return {
        "message": "If the account exists, a password reset email has been sent."
    }


# =====================================================
# RESET PASSWORD
# =====================================================

@router.post("/reset-password")
def reset_password(
    data: ResetPasswordRequest,
):

    reset = get_reset_token(
        data.token
    )

    if reset is None:

        raise HTTPException(
            status_code=400,
            detail="Invalid reset token.",
        )

    if reset.expires_at < datetime.utcnow():

        delete_reset_token(
            data.token
        )

        raise HTTPException(
            status_code=400,
            detail="Reset token has expired.",
        )

    db = SessionLocal()

    user = (
        db.query(User)
        .filter(User.email == reset.email)
        .first()
    )

    if user is None:

        db.close()

        raise HTTPException(
            status_code=404,
            detail="User not found.",
        )

    user.password_hash = hash_password(
        data.new_password
    )

    db.commit()
    db.close()

    delete_reset_token(
        data.token
    )

    logger.info(
        f"Password reset successful: {user.email}"
    )

    return {
        "message": "Password has been reset successfully."
    }