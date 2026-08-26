"""Rate limiting on auth endpoints (10/min per IP for login)."""

from app.core.rate_limit import limiter


class TestLoginRateLimit:
    async def test_11th_login_within_minute_is_429(self, client):
        # Distinct emails so account lockout never interferes with the count.
        statuses = []
        for i in range(11):
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": f"ratelimit-{i}@nowhere.com", "password": "Whatever!123"},
            )
            statuses.append(r.status_code)
        assert all(s == 401 for s in statuses[:10]), statuses
        assert statuses[10] == 429
        r11 = await client.post(
            "/api/v1/auth/login",
            json={"email": "ratelimit-extra@nowhere.com", "password": "Whatever!123"},
        )
        assert r11.status_code == 429
        assert "retry-after" in {k.lower() for k in r11.headers}

    async def test_limiter_reset_between_tests(self, client):
        # clean_state resets the limiter; this must NOT be rate limited.
        limiter.reset()
        r = await client.post(
            "/api/v1/auth/login", json={"email": "fresh@nowhere.com", "password": "Whatever!123"}
        )
        assert r.status_code == 401
