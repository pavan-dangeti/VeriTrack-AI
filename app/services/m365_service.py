"""Microsoft Entra ID (Azure AD) OIDC integration.

Authorization-code flow with PKCE. The id_token is validated against the
tenant JWKS (RS256 signature), plus issuer, audience, expiry and nonce.
Endpoints are disabled unless M365_CLIENT_ID / M365_CLIENT_SECRET are set.
"""

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt as pyjwt

from app.core.config import settings
from app.core.security import new_state_token


class M365Error(Exception):
    pass


def _authority() -> str:
    return f"https://login.microsoftonline.com/{settings.m365_tenant_id or 'common'}/v2.0"


def _authorize_base(tenant: str) -> str:
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"


@dataclass
class SsoChallenge:
    authorization_url: str
    state: str
    nonce: str
    code_verifier: str  # caller stores these in short-lived cookies for the callback


def create_challenge() -> SsoChallenge:
    tenant = settings.m365_tenant_id or "common"
    verifier = new_state_token()
    params = {
        "client_id": settings.m365_client_id or "",
        "response_type": "code",
        "redirect_uri": settings.m365_redirect_uri,
        "response_mode": "query",
        "scope": "openid email profile",
        "state": new_state_token(),
        "nonce": new_state_token(),
        "code_challenge": _s256(verifier),
        "code_challenge_method": "S256",
    }
    url = f"{_authorize_base(tenant)}/authorize?{urlencode(params)}"
    return SsoChallenge(
        authorization_url=url,
        state=params["state"],
        nonce=params["nonce"],
        code_verifier=verifier,
    )


def _s256(verifier: str) -> str:
    import base64
    import hashlib

    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def exchange_code(code: str, code_verifier: str) -> str:
    """Exchanges the auth code and returns the raw id_token (validated separately)."""
    if not settings.m365_enabled:
        raise M365Error("M365 SSO is not configured")

    tenant = settings.m365_tenant_id or "common"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_authorize_base(tenant)}/token",
            data={
                "grant_type": "authorization_code",
                "client_id": settings.m365_client_id,
                "client_secret": settings.m365_client_secret,
                "code": code,
                "redirect_uri": settings.m365_redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code != 200:
        raise M365Error("token_exchange_failed")
    id_token = resp.json().get("id_token")
    if not id_token:
        raise M365Error("no_id_token")
    return id_token


_jwks_cache: pyjwt.PyJWKClient | None = None


def _jwks_client() -> pyjwt.PyJWKClient:
    global _jwks_cache
    if _jwks_cache is None:
        tenant = settings.m365_tenant_id or "common"
        _jwks_cache = pyjwt.PyJWKClient(
            f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys",
            cache_keys=True,
            lifespan=3600,
        )
    return _jwks_cache


def validate_id_token(id_token: str, expected_nonce: str | None = None) -> dict:
    key = _jwks_client().get_signing_key_from_jwt(id_token)
    claims = pyjwt.decode(
        id_token,
        key.key,
        algorithms=["RS256"],
        audience=settings.m365_client_id,
        issuer=_authority(),
        options={"require": ["exp", "iat", "aud", "iss", "sub"]},
    )
    if expected_nonce is not None and claims.get("nonce") != expected_nonce:
        raise pyjwt.InvalidTokenError("nonce mismatch")
    return claims


async def domain_is_approved(db, email: str) -> bool:
    from sqlalchemy import select

    from app.models.m365_domain import ApprovedM365Domain

    domain = email.rsplit("@", 1)[-1].strip().lower()
    stmt = select(ApprovedM365Domain).where(
        ApprovedM365Domain.domain == domain,
        ApprovedM365Domain.is_active.is_(True),
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None
