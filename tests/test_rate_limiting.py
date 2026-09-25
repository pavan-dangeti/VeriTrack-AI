"""Rate limiting on auth endpoints, and client-address resolution behind proxies."""

import pytest

from app.core.proxy import client_from_forwarded
from app.core.rate_limit import LOGIN_LIMIT, limiter

LOGIN_MAX = int(LOGIN_LIMIT.split("/")[0])


async def _login(client, email: str, headers: dict | None = None) -> int:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "Whatever!123"},
                          headers=headers or {})
    return r.status_code


class TestLoginRateLimit:
    async def test_login_over_limit_within_minute_is_429(self, client):
        # Distinct emails so account lockout never interferes with the count.
        statuses = [await _login(client, f"ratelimit-{i}@nowhere.com") for i in range(LOGIN_MAX + 1)]
        assert all(s == 401 for s in statuses[:LOGIN_MAX]), statuses
        assert statuses[LOGIN_MAX] == 429
        r = await client.post("/api/v1/auth/login",
                              json={"email": "ratelimit-extra@nowhere.com", "password": "Whatever!123"})
        assert r.status_code == 429
        assert "retry-after" in {k.lower() for k in r.headers}

    async def test_forged_forwarded_for_cannot_dodge_the_limit(self, client):
        # The proxy (one hop) appends the real address; the client controls only
        # the entries to its left.
        statuses = [
            await _login(client, f"spoof-{i}@nowhere.com",
                         {"X-Forwarded-For": f"10.0.{i}.1, 203.0.113.9"})
            for i in range(LOGIN_MAX + 1)
        ]
        assert statuses[-1] == 429, statuses

    async def test_different_real_clients_have_separate_buckets(self, client):
        for i in range(LOGIN_MAX):
            assert await _login(client, f"a-{i}@nowhere.com", {"X-Forwarded-For": "198.51.100.1"}) == 401
        assert await _login(client, "b@nowhere.com", {"X-Forwarded-For": "198.51.100.2"}) == 401

    async def test_limiter_reset_between_tests(self, client):
        limiter.reset()
        assert await _login(client, "fresh@nowhere.com") == 401


@pytest.mark.parametrize(
    ("header", "hops", "expected"),
    [
        ("203.0.113.9", 1, "203.0.113.9"),
        ("6.6.6.6, 203.0.113.9", 1, "203.0.113.9"),          # forged left entry ignored
        ("6.6.6.6, 203.0.113.9, 76.76.21.1", 2, "203.0.113.9"),  # Vercel → Render
        ("203.0.113.9", 2, "203.0.113.9"),                    # shorter chain than hops
        ("", 1, None),
        ("203.0.113.9", 0, None),                             # direct: socket address
    ],
)
def test_client_from_forwarded(header, hops, expected):
    assert client_from_forwarded(header, hops) == expected


async def test_audit_log_records_resolved_client_ip(client, ma_user_id):
    from sqlalchemy import select

    from app.models.audit_log import AuditLog
    from tests.conftest import MA_EMAIL, MA_PASSWORD, open_session

    r = await client.post("/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD},
                          headers={"X-Forwarded-For": "6.6.6.6, 198.51.100.77"})
    assert r.status_code == 200
    async with open_session() as db:
        ips = (await db.execute(select(AuditLog.ip_address))).scalars().all()
    assert any(str(ip) == "198.51.100.77" for ip in ips), ips
