"""JWT lifecycle: expiry, tampering, refresh rotation, reuse detection, logout."""

from datetime import UTC, datetime, timedelta

import jwt as pyjwt
from sqlalchemy import update

from app.core.config import settings
from app.models.refresh_token import RefreshToken
from tests.conftest import (
    MA_EMAIL,
    MA_PASSWORD,
    auth_headers,
    login_access_token,
    test_session,
)


class TestAccessToken:
    async def test_expired_access_token_rejected(self, client, ma_user_id):
        payload = {
            "sub": str(ma_user_id),
            "role": "MASTER_ADMIN",
            "type": "access",
            "jti": "test-jti-expired",
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "iss": "veritrack",
            "aud": "veritrack",
        }
        expired = pyjwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")
        r = await client.get("/api/v1/auth/me", headers=auth_headers(expired))
        assert r.status_code == 401

    async def test_tampered_token_rejected(self, client, ma_user_id):
        token = await login_access_token(client, MA_EMAIL, MA_PASSWORD)
        header, payload_b64, signature = token.split(".")
        forged_payload = payload_b64[:-2] + ("AA" if not payload_b64.endswith("AA") else "BB")
        r = await client.get(
            "/api/v1/auth/me", headers=auth_headers(f"{header}.{forged_payload}.{signature}")
        )
        assert r.status_code == 401

    async def test_refresh_type_token_cannot_be_used_as_access(self, client, ma_user_id):
        resp = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        refresh_cookie = resp.cookies.get("veritrack_refresh")
        assert refresh_cookie
        r = await client.get("/api/v1/auth/me", headers=auth_headers(refresh_cookie))
        assert r.status_code == 401


async def _csrf_and_refresh(client):
    csrf_resp = await client.post("/api/v1/auth/csrf")
    csrf = csrf_resp.json()["csrf_token"]
    return {"X-CSRF-Token": csrf}


class TestRefreshRotation:
    async def test_rotation_issues_new_usable_pair(self, client, ma_user_id):
        login = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        old_cookie = login.cookies.get("veritrack_refresh")
        csrf = (await client.post("/api/v1/auth/csrf")).json()["csrf_token"]

        rotated = await client.post(
            "/api/v1/auth/refresh",
            headers={"X-CSRF-Token": csrf},
        )
        assert rotated.status_code == 200, rotated.text
        new_access = rotated.json()["access_token"]
        new_cookie = rotated.cookies.get("veritrack_refresh")
        assert new_cookie and new_cookie != old_cookie

        me = await client.get("/api/v1/auth/me", headers=auth_headers(new_access))
        assert me.status_code == 200

    async def test_csrf_required_for_refresh(self, client, ma_user_id):
        await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        r = await client.post("/api/v1/auth/refresh")  # no CSRF header
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "csrf_failed"

    async def test_old_refresh_token_single_use(self, client, ma_user_id):
        login = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        old_cookie = login.cookies.get("veritrack_refresh")

        # First rotation consumes the original token.
        csrf = (await client.post("/api/v1/auth/csrf")).json()["csrf_token"]
        first = await client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
        assert first.status_code == 200

        # Replay the ORIGINAL cookie -> reuse detection kills the whole family.
        client.cookies.set("veritrack_refresh", old_cookie)
        replay = await client.post(
            "/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf}
        )
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "token_reuse_detected"

        # Even the successor token is now dead (family revocation).
        successor = first.cookies.get("veritrack_refresh")
        client.cookies.set("veritrack_refresh", successor)
        after_kill = await client.post(
            "/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf}
        )
        assert after_kill.status_code == 401

    async def test_logout_revokes_session(self, client, ma_user_id):
        login = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        access = login.json()["access_token"]
        refresh_cookie_value = login.cookies.get("veritrack_refresh")
        assert refresh_cookie_value

        csrf = (await client.post("/api/v1/auth/csrf")).json()["csrf_token"]
        out = await client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": csrf, "Authorization": f"Bearer {access}"},
        )
        assert out.status_code == 200

        # Replay the logged-out refresh token with a fresh CSRF pair.
        client.cookies.set("veritrack_refresh", refresh_cookie_value)
        fresh_csrf = (await client.post("/api/v1/auth/csrf")).json()["csrf_token"]
        again = await client.post(
            "/api/v1/auth/refresh", headers={"X-CSRF-Token": fresh_csrf}
        )
        # Revoked-row replay trips reuse detection -> whole family stays dead.
        assert again.status_code == 401
        assert again.json()["error"]["code"] == "token_reuse_detected"

    async def test_expiring_refresh_row_is_honored(self, client, ma_user_id):
        """A refresh token whose DB row expires cannot rotate."""
        await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        async with test_session() as db:
            await db.execute(
                update(RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(days=1))
            )
            await db.commit()
        csrf = (await client.post("/api/v1/auth/csrf")).json()["csrf_token"]
        r = await client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
        assert r.status_code == 401
