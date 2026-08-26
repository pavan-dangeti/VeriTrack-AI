"""Authentication routes.

Cookie policy for browser flows:
- refresh token: HttpOnly + Secure(prod) + SameSite=Strict, path-scoped to /api/v1/auth
- CSRF token: readable by JS on purpose (double-submit pattern)

Access tokens travel in the Authorization header; CSRF is enforced only on
endpoints that rely on cookies (refresh/logout), so non-browser API clients
are unaffected.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import DB, Ctx, CurrentUser, verify_csrf
from app.core.config import settings
from app.core.rate_limit import CSRF_LIMIT, LOGIN_LIMIT, REFRESH_LIMIT, limiter
from app.core.security import constant_time_equals, new_state_token
from app.schemas.auth import CsrfResponse, LoginRequest, MessageResponse, TokenResponse
from app.services import audit_service, m365_service
from app.services.auth_service import (
    AuthError,
    authenticate_password,
    get_user_by_email,
    revoke_by_raw_token,
    rotate_refresh,
)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "veritrack_refresh"
CSRF_COOKIE = "veritrack_csrf"
SSO_STATE_COOKIE = "veritrack_sso_state"
SSO_NONCE_COOKIE = "veritrack_sso_nonce"
SSO_VERIFIER_COOKIE = "veritrack_sso_verifier"


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=raw_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/api/v1/auth",
        max_age=settings.refresh_token_expire_days * 24 * 3600,
    )


def _issue_csrf(response: Response) -> str:
    token = new_state_token()
    response.set_cookie(
        key=CSRF_COOKIE,
        value=token,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
        max_age=12 * 3600,
    )
    return token


def _token_response(pair) -> TokenResponse:
    return TokenResponse(
        access_token=pair.access_token,
        token_type="bearer",  # noqa: S106 - scheme name, not a secret
        expires_in=pair.expires_in,
    )


@router.post("/csrf", response_model=CsrfResponse)
@limiter.limit(CSRF_LIMIT)
async def issue_csrf(request: Request, response: Response) -> CsrfResponse:
    """Hands a fresh double-submit CSRF token to browser clients."""
    _ = request
    return CsrfResponse(csrf_token=_issue_csrf(response))


@router.post("/login", response_model=TokenResponse)
@limiter.limit(LOGIN_LIMIT)
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: DB,
    ctx: Ctx,
):
    """Email+password login. Rate-limited; every attempt is audited."""
    _ = request
    try:
        _, pair = await authenticate_password(
            db,
            email=body.email,
            password=body.password,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
        )
    except AuthError as exc:
        raise HTTPException(
            exc.status_code, detail={"code": exc.code, "message": exc.message}
        ) from exc
    _issue_csrf(response)
    _set_refresh_cookie(response, pair.refresh_token)
    return _token_response(pair)


@router.get("/me")
async def me(user: CurrentUser):
    return user.public_dict()


# --- Microsoft Entra ID SSO ---------------------------------------------------


def _sso_cookie_params() -> dict:
    # Lax (not Strict): the IdP redirect is a cross-site top-level navigation
    # that must carry these back to /m365/callback.
    return {
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": "lax",
        "path": "/api/v1/auth",
        "max_age": int(timedelta(minutes=10).total_seconds()),
    }


@router.get("/m365/login")
@limiter.limit(LOGIN_LIMIT)
async def m365_login(request: Request):
    _ = request
    if not settings.m365_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "sso_disabled", "message": "M365 SSO is not configured"},
        )
    challenge = m365_service.create_challenge()
    response = RedirectResponse(challenge.authorization_url, status_code=303)
    params = _sso_cookie_params()
    response.set_cookie(SSO_STATE_COOKIE, challenge.state, **params)
    response.set_cookie(SSO_NONCE_COOKIE, challenge.nonce, **params)
    response.set_cookie(SSO_VERIFIER_COOKIE, challenge.code_verifier, **params)
    return response


@router.get("/m365/callback")
@limiter.limit(LOGIN_LIMIT)
async def m365_callback(request: Request, db: DB, ctx: Ctx, response: Response):
    if not settings.m365_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "sso_disabled", "message": "M365 SSO is not configured"},
        )

    state = request.query_params.get("state")
    code = request.query_params.get("code")
    cookie_state = request.cookies.get(SSO_STATE_COOKIE)
    cookie_nonce = request.cookies.get(SSO_NONCE_COOKIE)
    cookie_verifier = request.cookies.get(SSO_VERIFIER_COOKIE)
    for name in (SSO_STATE_COOKIE, SSO_NONCE_COOKIE, SSO_VERIFIER_COOKIE):
        response.delete_cookie(name, path="/api/v1/auth")

    if not state or not cookie_state or not constant_time_equals(state, cookie_state):
        await audit_service.record(
            db,
            action=audit_service.ACTION_LOGIN_M365,
            result=audit_service.AuditResult.DENIED,
            ip_address=ctx.ip_address,
            metadata={"reason": "state_mismatch"},
        )
        raise HTTPException(
            400, detail={"code": "invalid_sso", "message": "Invalid SSO state"}
        )
    if not code or not cookie_nonce or not cookie_verifier:
        await audit_service.record(
            db,
            action=audit_service.ACTION_LOGIN_M365,
            result=audit_service.AuditResult.FAILURE,
            ip_address=ctx.ip_address,
            metadata={"reason": "missing_code_or_challenge"},
        )
        raise HTTPException(
            400, detail={"code": "invalid_sso", "message": "Invalid SSO request"}
        )

    try:
        id_token = await m365_service.exchange_code(code, cookie_verifier)
        claims = m365_service.validate_id_token(id_token, expected_nonce=cookie_nonce)
    except Exception as exc:  # noqa: BLE001 — any failure is an auth failure
        await audit_service.record(
            db,
            action=audit_service.ACTION_LOGIN_M365,
            result=audit_service.AuditResult.FAILURE,
            ip_address=ctx.ip_address,
            metadata={"reason": "token_validation_failed", "detail": str(exc)[:200]},
        )
        raise HTTPException(
            401,
            detail={"code": "invalid_sso", "message": "SSO validation failed"},
        ) from exc

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(
            401, detail={"code": "no_email", "message": "No email claim in SSO token"}
        )

    # Checkpoint: is this email's domain pre-approved?
    if not await m365_service.domain_is_approved(db, email):
        await audit_service.record(
            db,
            action=audit_service.ACTION_LOGIN_M365,
            result=audit_service.AuditResult.DENIED,
            target_entity="user",
            target_id=email,
            ip_address=ctx.ip_address,
            metadata={"reason": "domain_not_approved"},
        )
        raise HTTPException(
            403,
            detail={
                "code": "domain_not_approved",
                "message": "Email domain is not pre-approved for SSO",
            },
        )

    user = await get_user_by_email(db, email)
    if user is None or not user.is_active:
        await audit_service.record(
            db,
            action=audit_service.ACTION_LOGIN_M365,
            result=audit_service.AuditResult.DENIED,
            actor_user_id=user.id if user else None,
            target_entity="user",
            target_id=email,
            ip_address=ctx.ip_address,
            metadata={"reason": "no_active_account"},
        )
        raise HTTPException(
            403,
            detail={
                "code": "account_unavailable",
                "message": "No active account for this identity",
            },
        )

    from app.services.auth_service import _issue_pair

    pair = _issue_pair(db, user)
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    await audit_service.record(
        db,
        action=audit_service.ACTION_LOGIN_M365,
        result=audit_service.AuditResult.SUCCESS,
        actor_user_id=user.id,
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
    )
    _issue_csrf(response)
    _set_refresh_cookie(response, pair.refresh_token)
    return _token_response(pair)


@router.post(
    "/refresh", response_model=TokenResponse, dependencies=[Depends(verify_csrf)]
)
@limiter.limit(REFRESH_LIMIT)
async def refresh(request: Request, response: Response, db: DB, ctx: Ctx):
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(401, detail={"code": "unauthorized", "message": "No session"})
    try:
        _, pair = await rotate_refresh(
            db,
            raw_refresh_token=raw,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
        )
    except AuthError as exc:
        response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
        raise HTTPException(
            exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    _set_refresh_cookie(response, pair.refresh_token)
    return _token_response(pair)


@router.post("/logout", dependencies=[Depends(verify_csrf)])
async def logout(request: Request, response: Response, db: DB, ctx: Ctx, user: CurrentUser):
    raw = request.cookies.get(REFRESH_COOKIE)
    await revoke_by_raw_token(db, raw)
    await audit_service.record(
        db,
        action=audit_service.ACTION_LOGOUT,
        result=audit_service.AuditResult.SUCCESS,
        actor_user_id=user.id,
        ip_address=ctx.ip_address,
    )
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return MessageResponse(message="Logged out")

