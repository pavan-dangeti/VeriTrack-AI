"""DB-level role hierarchy enforcement + endpoint-level creation authority."""

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models.user import UserRole
from tests.conftest import (
    MA_EMAIL,
    MA_PASSWORD,
    test_session,
)

FAKE_HASH = "$2b$12$" + "a" * 53


async def _try_insert(db, sql, params=None):
    """Execute an INSERT; return the DB error or None when accepted."""
    try:
        await db.execute(text(sql), params or {})
        await db.commit()
        return None
    except DBAPIError as exc:
        await db.rollback()
        return exc


@pytest_asyncio.fixture
async def ids(ma_user_id):
    async with test_session() as db:
        from sqlalchemy import select

        from app.services.user_service import create_user

        ma = (
            await db.execute(
                select(User).where(User.email == MA_EMAIL)
            )
        ).scalar_one()
        manager, _ = await create_user(
            db, creator=ma, email="trigger-manager@veritrack.io", role=UserRole.MANAGER
        )
        exec_row = (
            await db.execute(
                text(
                    """INSERT INTO users (role, email, auth_type, password_hash, created_by)
                       VALUES ('EXECUTIVE', 'trigger-exec@veritrack.io', 'PASSWORD',
                               :h, :by) RETURNING id"""
                ),
                {"h": FAKE_HASH, "by": str(ma_user_id)},
            )
        ).scalar_one()
        await db.commit()
    return {"manager": manager.id, "executive": exec_row}


# Import after fixtures to keep model import local where practical
from app.models.user import User  # noqa: E402


class TestMasterAdminUniqueness:
    async def test_second_master_admin_rejected_by_db(self, ma_user_id):
        async with test_session() as db:
            err = await _try_insert(
                db,
                """INSERT INTO users (role, email, auth_type, password_hash)
                   VALUES ('MASTER_ADMIN', 'second-ma@x.com', 'PASSWORD', :h)""",
                {"h": FAKE_HASH},
            )
        assert err is not None, "2nd MA must violate uq_users_single_master_admin"
        assert "uq_users_single_master_admin" in str(err)


class TestHierarchyTriggers:
    async def test_hr_with_non_manager_reference_rejected(self, ma_user_id, ids):
        async with test_session() as db:
            err = await _try_insert(
                db,
                """INSERT INTO users (role, email, auth_type, password_hash,
                                      manager_id, created_by)
                   VALUES ('HR', 'hr-bad@veritrack.io', 'PASSWORD', :h, :mgr, :by)""",
                {"h": FAKE_HASH, "mgr": str(ids["executive"]), "by": str(ids["manager"])},
            )
        assert err is not None and "MANAGER" in str(err)

    async def test_hr_without_manager_id_rejected_by_check(self, ma_user_id, ids):
        async with test_session() as db:
            err = await _try_insert(
                db,
                """INSERT INTO users (role, email, auth_type, password_hash, created_by)
                   VALUES ('HR', 'hr-null@veritrack.io', 'PASSWORD', :h, :by)""",
                {"h": FAKE_HASH, "by": str(ids["manager"])},
            )
        # The BEFORE trigger rejects first; the CHECK is defense in depth.
        assert err is not None and "manager_id" in str(err)

    async def test_hr_created_by_master_admin_rejected(self, ma_user_id, ids):
        async with test_session() as db:
            err = await _try_insert(
                db,
                """INSERT INTO users (role, email, auth_type, password_hash,
                                      manager_id, created_by)
                   VALUES ('HR', 'hr-ma-created@veritrack.io', 'PASSWORD', :h,
                           :mgr, :by)""",
                {"h": FAKE_HASH, "mgr": str(ids["manager"]), "by": str(ma_user_id)},
            )
        assert err is not None and "created by a MANAGER" in str(err)

    async def test_manager_created_by_manager_rejected_at_db_level(self, ma_user_id, ids):
        async with test_session() as db:
            err = await _try_insert(
                db,
                """INSERT INTO users (role, email, auth_type, password_hash, created_by)
                   VALUES ('MANAGER', 'mgr-by-mgr@veritrack.io', 'PASSWORD', :h, :by)""",
                {"h": FAKE_HASH, "by": str(ids["manager"])},
            )
        assert err is not None and "MASTER_ADMIN" in str(err)


class TestUserCreationEndpoints:
    async def _login_ma(self, client) -> dict:
        resp = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    async def test_ma_creates_manager_and_executive(self, client, ma_user_id):
        headers = await self._login_ma(client)
        for email, role in [
            ("ep-create-mgr@veritrack.io", "MANAGER"),
            ("ep-create-exec@veritrack.io", "EXECUTIVE"),
        ]:
            r = await client.post(
                "/api/v1/users", json={"email": email, "role": role}, headers=headers
            )
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["user"]["role"] == role
            assert len(body["initial_password"]) >= 12

    async def test_ma_cannot_create_hr_via_endpoint(self, client, ma_user_id):
        headers = await self._login_ma(client)
        r = await client.post(
            "/api/v1/users",
            json={"email": "no-hr@veritrack.io", "role": "HR"},
            headers=headers,
        )
        assert r.status_code == 403

    async def test_manager_creates_only_hr_scoped_to_self(self, client, ma_user_id):
        headers = await self._login_ma(client)
        created = await client.post(
            "/api/v1/users",
            json={"email": "scoping-manager@veritrack.io", "role": "MANAGER"},
            headers=headers,
        )
        assert created.status_code == 201
        mgr_password = created.json()["initial_password"]

        mgr_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "scoping-manager@veritrack.io", "password": mgr_password},
        )
        assert mgr_login.status_code == 200
        mgr_headers = {"Authorization": f"Bearer {mgr_login.json()['access_token']}"}

        # Manager creating another Manager -> forbidden
        r = await client.post(
            "/api/v1/users",
            json={"email": "nested@veritrack.io", "role": "MANAGER"},
            headers=mgr_headers,
        )
        assert r.status_code == 403

        # Manager creating HR -> allowed, manager_id auto-scoped to self
        r = await client.post(
            "/api/v1/users",
            json={"email": "scoped-hr@veritrack.io", "role": "HR"},
            headers=mgr_headers,
        )
        assert r.status_code == 201, r.text

        # Query-layer scoping: manager sees ONLY their own HRs
        listing = await client.get("/api/v1/users", headers=mgr_headers)
        emails = [u["email"] for u in listing.json()["items"]]
        assert emails == ["scoped-hr@veritrack.io"]

    async def test_duplicate_email_conflict_case_insensitive(self, client, ma_user_id):
        headers = await self._login_ma(client)
        first = await client.post(
            "/api/v1/users",
            json={"email": "dup@veritrack.io", "role": "MANAGER"},
            headers=headers,
        )
        assert first.status_code == 201
        second = await client.post(
            "/api/v1/users",
            json={"email": "DUP@veritrack.io", "role": "MANAGER"},
            headers=headers,
        )
        assert second.status_code == 409

    async def test_unauthenticated_create_rejected(self, client, ma_user_id):
        r = await client.post(
            "/api/v1/users", json={"email": "anon@x.com", "role": "MANAGER"}
        )
        assert r.status_code == 401


class TestAccountStatus:
    async def test_disable_flow_and_guards(self, client, ma_user_id):
        login = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        created = await client.post(
            "/api/v1/users",
            json={"email": "disable-me@veritrack.io", "role": "EXECUTIVE"},
            headers=headers,
        )
        target_id = created.json()["user"]["id"]

        # No token -> cannot toggle status
        r = await client.patch(
            f"/api/v1/users/{target_id}/status", json={"is_active": False}
        )
        assert r.status_code == 401

        disabled = await client.patch(
            f"/api/v1/users/{target_id}/status",
            json={"is_active": False},
            headers=headers,
        )
        assert disabled.status_code == 200 and disabled.json()["is_active"] is False

        # Disabled account cannot log in
        pw = created.json()["initial_password"]
        denied = await client.post(
            "/api/v1/auth/login",
            json={"email": "disable-me@veritrack.io", "password": pw},
        )
        assert denied.status_code == 401

        # MA cannot disable their own account
        me = await client.get("/api/v1/auth/me", headers=headers)
        r = await client.patch(
            f"/api/v1/users/{me.json()['id']}/status",
            json={"is_active": False},
            headers=headers,
        )
        assert r.status_code == 400
