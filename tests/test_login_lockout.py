"""Password login: generic errors, account lockout after 5 failures/15min."""

import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.models.user import User
from tests.conftest import (
    MA_EMAIL,
    MA_PASSWORD,
    auth_headers,
    login_access_token,
    open_session,
)

WRONG = "Definitely!Wrong123"


async def _lock_user_now(user_id):
    async with open_session() as db:
        await db.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                failed_login_attempts=5,
                locked_until=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        await db.commit()


class TestLogin:
    async def test_successful_login_returns_token_and_me(self, client, ma_user_id):
        resp = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 15 * 60

        me = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
        )
        assert me.status_code == 200
        assert me.json()["role"] == "MASTER_ADMIN"

    async def test_wrong_password_generic_error(self, client, ma_user_id):
        resp = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": WRONG}
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "invalid_credentials"

    async def test_unknown_email_same_error_as_wrong_password(self, client, ma_user_id):
        ghost = await client.post(
            "/api/v1/auth/login", json={"email": "ghost@nowhere.example.com", "password": WRONG}
        )
        known_bad = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": WRONG}
        )
        assert ghost.status_code == known_bad.status_code == 401
        # Anti-enumeration: code + message must be identical. request_id differs
        # per request by design and is not part of the indistinguishability claim.
        for key in ("code", "message"):
            assert ghost.json()["error"][key] == known_bad.json()["error"][key]

    async def test_malformed_body_rejected(self, client, ma_user_id):
        r = await client.post("/api/v1/auth/login", json={"email": "not-an-email"})
        assert r.status_code == 422


class TestLockout:
    async def test_lockout_after_five_failures_then_recovery(self, client, ma_user_id):
        for i in range(5):
            r = await client.post(
                "/api/v1/auth/login",
                json={"email": MA_EMAIL, "password": f"{WRONG}{i}"},
            )
            assert r.status_code == 401

        # The correct password still works while locked (no DoS of the owner), and a wrong one gets the
        # uniform 401, so lockout state is not an enumeration oracle.
        wrong_while_locked = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": WRONG}
        )
        assert wrong_while_locked.status_code == 401
        assert wrong_while_locked.json()["error"]["code"] == "invalid_credentials"

        ok_despite_lock = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        assert ok_despite_lock.status_code == 200

        async with open_session() as db:
            user = (
                await db.execute(select(User).where(User.email == MA_EMAIL))
            ).scalar_one()
            await db.execute(
                update(User)
                .where(User.id == user.id)
                .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
            )
            await db.commit()

        recovered = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        assert recovered.status_code == 200

        async with open_session() as db:
            user = (
                await db.execute(select(User).where(User.email == MA_EMAIL))
            ).scalar_one()
            assert user.failed_login_attempts == 0
            assert user.locked_until is None

    async def test_successful_login_during_lockout_clears_lock_and_counter(self, client, ma_user_id):
        """Regression: correct password during an active lock must FULLY clear
        lockout state (not just bypass it for that one request)."""
        await _lock_user_now(ma_user_id)

        async with open_session() as db:
            user = (await db.execute(select(User).where(User.id == ma_user_id))).scalar_one()
            assert user.locked_until is not None and user.failed_login_attempts == 5

        ok = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        assert ok.status_code == 200

        async with open_session() as db:
            user = (await db.execute(select(User).where(User.id == ma_user_id))).scalar_one()
            assert user.locked_until is None
            assert user.failed_login_attempts == 0

    async def test_lockout_window_resets_on_success(self, client, ma_user_id):
        for i in range(3):
            await client.post(
                "/api/v1/auth/login",
                json={"email": MA_EMAIL, "password": f"{WRONG}{i}"},
            )
        ok = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        assert ok.status_code == 200

        async with open_session() as db:
            user = (
                await db.execute(select(User).where(User.email == MA_EMAIL))
            ).scalar_one()
            assert user.failed_login_attempts == 0


class TestNoConnectionHeldDuringBcrypt:
    """bcrypt takes a quarter of a second per call, and far longer when 200 users sign in at once on 2 vCPUs.
    A database connection held through it starves the pool: the 200-user load test hit pool timeouts (HTTP
    500) until sign-in and user creation released the connection before hashing."""

    @staticmethod
    def _watch(monkeypatch, module, name, held=None):
        from app.db.session import engine

        held = [] if held is None else held
        real = getattr(module, name)

        def watched(*args, **kwargs):
            # and on bcrypt's own pool, not the default one that storage I/O shares
            assert threading.current_thread().name.startswith("bcrypt"), threading.current_thread().name
            held.append(engine.pool.checkedout())
            return real(*args, **kwargs)

        monkeypatch.setattr(module, name, watched)
        return held

    async def test_sign_in(self, client, ma_user_id, monkeypatch):
        from app.services import auth_service

        held = self._watch(monkeypatch, auth_service, "verify_password")
        self._watch(monkeypatch, auth_service, "hash_password", held)
        from app.core.rate_limit import limiter

        for email, password, status in ((MA_EMAIL, MA_PASSWORD, 200), (MA_EMAIL, "Wrong!Pass123", 401),
                                        ("nobody@veritrack.io", "Wrong!Pass123", 401)):
            limiter.reset()
            r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
            assert r.status_code == status, r.text
        assert held == [0, 0, 0], held   # right password, wrong password, unknown e-mail

    async def test_user_creation(self, client, ma_user_id, monkeypatch):
        from app.services import user_service

        held = self._watch(monkeypatch, user_service, "hash_password")
        token = await login_access_token(client, MA_EMAIL, MA_PASSWORD)
        r = await client.post("/api/v1/users", headers=auth_headers(token),
                              json={"email": "pool.check@veritrack.io", "role": "MANAGER"})
        assert r.status_code == 201 and held == [0], held
