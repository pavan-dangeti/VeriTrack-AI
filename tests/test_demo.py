"""Public demo account: limited, synthetic, and reset to the same state on schedule."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update

from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.employees import Employee
from app.models.leaves import CompanyLeave
from app.models.uploads import UploadBatch, UploadedFile
from app.services import demo_service
from app.services.storage import StorageError, get_storage
from tests.conftest import open_session
from tests.test_timesheet_leave_flow import real_ocr  # noqa: F401 — fixture

DEMO_EMAIL, DEMO_PASSWORD = "demo@example.com", "Demo!Passw0rd-1"


@pytest.fixture
def demo(monkeypatch, ma_user_id):
    monkeypatch.setattr(settings, "demo_email", DEMO_EMAIL)
    monkeypatch.setattr(settings, "demo_password", DEMO_PASSWORD)


async def _login(client):
    r = await client.post("/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _demo_user():
    async with open_session() as db:
        return await demo_service.sync_account(db)


async def _count(model, manager_id):
    async with open_session() as db:
        stmt = select(func.count()).select_from(model).where(model.manager_id == manager_id)
        return (await db.execute(stmt)).scalar_one()


async def test_disabled_without_credentials(client):
    assert (await client.get("/api/v1/demo")).json() == {"enabled": False}
    assert (await client.get("/api/v1/demo/samples/timesheet_000.png")).status_code == 404


async def test_info_and_samples_are_public(client, demo):
    info = (await client.get("/api/v1/demo")).json()
    assert info["enabled"] and info["email"] == DEMO_EMAIL and info["password"] == DEMO_PASSWORD
    r = await client.get(f"/api/v1/demo/samples/{info['samples'][0]}")
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")
    for bad in ("nope.png", "..%2F..%2Fapp%2Fmain.py", "ground_truth.json"):
        assert (await client.get(f"/api/v1/demo/samples/{bad}")).status_code == 404


async def test_demo_manager_cannot_create_users(client, demo):
    await _demo_user()
    h = await _login(client)
    r = await client.post("/api/v1/users", headers=h,
                          json={"email": "hr@example.com", "role": "HR", "full_name": "H"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "demo_account"


async def test_never_adopts_an_existing_real_account(client, demo, monkeypatch):
    await _demo_user()
    h = await _login(client)
    await client.post("/api/v1/uploads?kind=COMPANY_LEAVE", headers=h,
                      files=[("files", ("l.csv", demo_service.LEAVE_CSV.encode(), "text/csv"))])
    admin = await client.post("/api/v1/auth/login", json={"email": "ma@veritrack.io", "password": "Master!Pass123"})
    ah = {"Authorization": f"Bearer {admin.json()['access_token']}"}
    real = await client.post("/api/v1/users", headers=ah,
                             json={"email": "real.manager@example.com", "role": "MANAGER", "full_name": "R"})
    assert real.status_code == 201
    monkeypatch.setattr(settings, "demo_email", "real.manager@example.com")   # operator typo
    with pytest.raises(SystemExit, match="not the demo account"):
        await _demo_user()
    async with open_session() as db, open_session() as other:
        with pytest.raises(SystemExit):
            await demo_service.reset_if_due(db)
        # advisory locks are re-entrant per session, so check from another one that it was released
        lock = text("SELECT pg_try_advisory_lock(:k)")
        assert (await other.execute(lock, {"k": demo_service._LOCK_ID})).scalar_one()
        await other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": demo_service._LOCK_ID})


async def test_sync_keeps_password_in_line(client, demo, monkeypatch):
    await _demo_user()
    monkeypatch.setattr(settings, "demo_password", "Rotated!Passw0rd-2")
    await _demo_user()
    r = await client.post("/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": "Rotated!Passw0rd-2"})
    assert r.status_code == 200


async def test_reset_replaces_data_and_removes_stored_files(client, demo):
    user = await _demo_user()
    async with open_session() as db:
        await demo_service.reset(db, user, sheets=())
    async with open_session() as db:
        keys = list((await db.execute(
            select(UploadedFile.storage_key).where(UploadedFile.manager_id == user.id))).scalars())
    assert keys and all(get_storage().get_bytes(k) for k in keys)

    async with open_session() as db:
        await demo_service.reset(db, user, sheets=())

    assert await _count(Employee, user.id) == 4
    assert await _count(CompanyLeave, user.id) == 8
    assert await _count(UploadBatch, user.id) == 2           # repository + leave register, not doubled
    for key in keys:                                          # the first reset's files are gone
        with pytest.raises(StorageError):
            get_storage().get_bytes(key)


async def test_reset_runs_only_when_due(client, demo):
    async with open_session() as db:
        assert await demo_service.reset_if_due(db) is True    # never reset before
        assert await demo_service.reset_if_due(db) is False   # just done
        await db.execute(update(AuditLog).where(AuditLog.action == "DEMO_RESET")
                         .values(timestamp=datetime.now(UTC) - timedelta(hours=25)))
        await db.commit()
        assert await demo_service.reset_if_due(db) is True


@pytest.mark.usefixtures("real_ocr")
async def test_full_reset_finds_the_two_planted_violations_and_never_emails(client, demo, monkeypatch):
    from app.services import emailer

    for key in ("graph_tenant_id", "graph_client_id", "graph_client_secret"):
        monkeypatch.setattr(settings, key, "configured")
    monkeypatch.setattr(settings, "outbound_email_mode", "live")

    def no_live_email(*_a, **_k):
        raise AssertionError("the demo account must not send real email")

    monkeypatch.setattr(emailer, "GraphClient", no_live_email)
    user = await _demo_user()
    async with open_session() as db:
        result = await demo_service.reset(db, user)
    assert result["violations"] == 2


async def test_a_reset_that_fails_in_sql_still_releases_the_lock(client, demo, monkeypatch):
    async def failing_reset(db, user, **_):
        await db.execute(text("SELECT 1 / 0"))     # aborts the transaction

    monkeypatch.setattr(demo_service, "reset", failing_reset)
    async with open_session() as db, open_session() as other:
        with pytest.raises(Exception, match="division by zero"):
            await demo_service.reset_if_due(db)
        lock = text("SELECT pg_try_advisory_lock(:k)")
        assert (await other.execute(lock, {"k": demo_service._LOCK_ID})).scalar_one()
        await other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": demo_service._LOCK_ID})
