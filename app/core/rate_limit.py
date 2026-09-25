"""Rate limiting: RATE_LIMIT_STORAGE_URI is memory:// for one instance, redis://… when replicas share counters."""

from slowapi import Limiter

from app.core.config import settings


def _client_ip(request) -> str:
    return request.client.host if request.client else "unknown"


def _user_or_ip(request) -> str:
    """Buckets per user when possible (one office NAT must not pool everyone's uploads), else per IP.

    The JWT is decoded WITHOUT signature verification: this is only a bucket key, never an auth
    decision, and a forged token can only split the forger's own traffic into extra buckets.
    """
    import base64
    import json

    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = auth.removeprefix("Bearer ").split(".")[1]
            payload += "=" * (-len(payload) % 4)
            sub = json.loads(base64.urlsafe_b64decode(payload)).get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:  # noqa: S110 — bad/missing token => IP bucket
            pass
    return _client_ip(request)


limiter = Limiter(key_func=_client_ip, storage_uri=settings.rate_limit_storage_uri)
user_limiter = Limiter(key_func=_user_or_ip, storage_uri=settings.rate_limit_storage_uri)

LOGIN_LIMIT = "30/minute"
REFRESH_LIMIT = "120/minute"
CSRF_LIMIT = "120/minute"

UPLOAD_LIMIT = "30/minute"
ANALYZE_LIMIT = "10/minute"
EXPORT_LIMIT = "30/minute"
