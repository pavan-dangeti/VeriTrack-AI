"""Rate limiting for auth endpoints.

ponytail: in-memory storage — correct for single-instance deploys; swap
storage_uri to redis:// when running multiple API replicas.
"""

from slowapi import Limiter


def _client_ip(request) -> str:
    return request.client.host if request.client else "unknown"


def _user_or_ip(request) -> str:
    """Bucket per authenticated user when possible (one office NAT must not
    pool everyone's uploads); falls back to IP for anonymous traffic.

    The JWT payload is decoded WITHOUT verifying the signature — this is only
    a rate-limit bucket key, never an auth decision; worse case an attacker
    splits their own traffic into extra buckets, which hurts only them.
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


limiter = Limiter(key_func=_client_ip)
# User-keyed limiter for expensive endpoints (uploads, analysis, exports).
user_limiter = Limiter(key_func=_user_or_ip)

# Policy (spec): auth endpoints are the abuse surface.
LOGIN_LIMIT = "10/minute"
REFRESH_LIMIT = "30/minute"
CSRF_LIMIT = "30/minute"

# Expensive endpoints: OCR/Celery queue + report generation.
UPLOAD_LIMIT = "10/minute"
ANALYZE_LIMIT = "10/minute"
EXPORT_LIMIT = "30/minute"
