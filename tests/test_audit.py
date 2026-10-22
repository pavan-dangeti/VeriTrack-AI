"""Every key action must land in audit_logs with the right result."""

from sqlalchemy import func, select

from app.db.tenant import SYSTEM, tenant
from app.models.audit_log import AuditLog, AuditResult
from app.services import audit_service
from tests.conftest import (
    MA_EMAIL,
    MA_PASSWORD,
    auth_headers,
    open_session,
)


async def _count(result: AuditResult | None = None, action: str | None = None) -> int:
    async with open_session() as db:
        stmt = select(func.count()).select_from(AuditLog)
        if result is not None:
            stmt = stmt.where(AuditLog.result == result)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        return int((await db.execute(stmt)).scalar_one())


class TestLoginAuditing:
    async def test_success_and_failure_both_audited(self, client, ma_user_id):
        await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        assert await _count(AuditResult.SUCCESS, audit_service.ACTION_LOGIN) == 1

        await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": "Nope!12345678"}
        )
        assert await _count(AuditResult.FAILURE, audit_service.ACTION_LOGIN) == 1

    async def test_unknown_email_failure_recorded_without_actor(self, client, ma_user_id):
        await client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@nowhere.example.com", "password": "Whatever!123"},
        )
        # it belongs to no organisation, so no organisation's admin sees it
        assert await _count(AuditResult.FAILURE, audit_service.ACTION_LOGIN) == 0
        with tenant(SYSTEM):
            async with open_session() as db:
                entry = (await db.execute(select(AuditLog).where(AuditLog.action == audit_service.ACTION_LOGIN))
                         ).scalar_one()
        assert entry.result == AuditResult.FAILURE and entry.actor_user_id is None and entry.org_id is None

    async def test_logout_audited(self, client, ma_user_id):
        login = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        csrf = (await client.post("/api/v1/auth/csrf")).json()["csrf_token"]
        await client.post(
            "/api/v1/auth/logout",
            headers={
                "X-CSRF-Token": csrf,
                "Authorization": f"Bearer {login.json()['access_token']}",
            },
        )
        assert await _count(action=audit_service.ACTION_LOGOUT) == 1


class TestRbacDenialAuditing:
    async def test_denied_endpoint_access_writes_denied_row(self, client, ma_user_id):
        login = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        ma_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        created = await client.post(
            "/api/v1/users",
            json={"email": "denial-manager@veritrack.io", "role": "MANAGER"},
            headers=ma_headers,
        )
        mgr_pw = created.json()["initial_password"]

        mgr_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "denial-manager@veritrack.io", "password": mgr_pw},
        )
        mgr_headers = {"Authorization": f"Bearer {mgr_login.json()['access_token']}"}

        before = await _count(AuditResult.DENIED, audit_service.ACTION_RBAC_DENIED)
        r = await client.patch(
            "/api/v1/users/00000000-0000-0000-0000-000000000000/status",
            json={"is_active": False},
            headers=mgr_headers,
        )
        assert r.status_code == 403
        assert await _count(AuditResult.DENIED, audit_service.ACTION_RBAC_DENIED) == before + 1

    async def test_hr_cannot_read_audit_logs(self, client, ma_user_id):
        login = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        ma_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        created = await client.post(
            "/api/v1/users",
            json={"email": "audit-hr-manager@veritrack.io", "role": "MANAGER"},
            headers=ma_headers,
        )
        mgr_login = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "audit-hr-manager@veritrack.io",
                "password": created.json()["initial_password"],
            },
        )
        mgr_headers = {"Authorization": f"Bearer {mgr_login.json()['access_token']}"}
        hr_created = await client.post(
            "/api/v1/users",
            json={"email": "audit-hr@veritrack.io", "role": "HR"},
            headers=mgr_headers,
        )
        assert hr_created.status_code == 201
        hr_login = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "audit-hr@veritrack.io",
                "password": hr_created.json()["initial_password"],
            },
        )
        hr_headers = {"Authorization": f"Bearer {hr_login.json()['access_token']}"}
        r = await client.get("/api/v1/audit-logs", headers=hr_headers)
        assert r.status_code == 403


class TestUserManagementAuditing:
    async def test_create_and_disable_audited(self, client, ma_user_id):
        login = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        created = await client.post(
            "/api/v1/users",
            json={"email": "audited-user@veritrack.io", "role": "EXECUTIVE"},
            headers=headers,
        )
        assert created.status_code == 201
        assert await _count(action=audit_service.ACTION_CREATE_USER) == 1

        target_id = created.json()["user"]["id"]
        disabled = await client.patch(
            f"/api/v1/users/{target_id}/status",
            json={"is_active": False},
            headers=headers,
        )
        assert disabled.status_code == 200
        assert await _count(action=audit_service.ACTION_DISABLE_USER) == 1


class TestAuditListingEndpoint:
    async def test_master_admin_can_list_with_filters(self, client, ma_user_id):
        await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        resp = await client.get(
            "/api/v1/audit-logs?result=SUCCESS&limit=10",
            headers=await self._ma_headers(client),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit"] == 10
        assert all(item["result"] == "SUCCESS" for item in body["items"])

    async def _ma_headers(self, client):
        token = None
        login = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
        )
        token = login.json()["access_token"]
        return auth_headers(token)


class TestAuditMetadata:
    async def test_metadata_is_persisted(self, ma_user_id):
        async with open_session() as db:
            await audit_service.record(
                db, action="UPLOAD_REJECTED", result=AuditResult.FAILURE,
                actor_user_id=ma_user_id, metadata={"reason": "bad_magic"},
            )
        async with open_session() as db:
            row = (await db.execute(select(AuditLog).where(AuditLog.action == "UPLOAD_REJECTED"))).scalar_one()
        assert row.event_metadata == {"reason": "bad_magic"}
