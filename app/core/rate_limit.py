"""Rate limiting for auth endpoints.

ponytail: in-memory storage — correct for single-instance deploys; swap
storage_uri to redis:// when running multiple API replicas.
"""

from slowapi import Limiter


def _client_ip(request) -> str:
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_client_ip)

# Policy (spec): auth endpoints are the abuse surface.
LOGIN_LIMIT = "10/minute"
REFRESH_LIMIT = "30/minute"
CSRF_LIMIT = "30/minute"
