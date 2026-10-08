"""The Master Admin follows ADMIN_EMAIL / ADMIN_PASSWORD: rotating them in the host takes effect on restart."""

import pytest
from sqlalchemy import select

from app.cli import sync_master_admin
from app.core.config import Settings
from app.models.audit_log import AuditLog
from app.models.refresh_token import RefreshToken
from tests.conftest import open_session

EMAIL, OLD, NEW = "owner@veritrack.io", "Old!Passw0rd-123", "New!Passw0rd-456"


async def _login(client, email, password):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_creates_then_leaves_unchanged(client):
    assert await sync_master_admin(EMAIL, OLD) == "created"
    assert await sync_master_admin(EMAIL, OLD) == "unchanged"
    assert (await _login(client, EMAIL, OLD)).status_code == 200


async def test_password_rotation_revokes_sessions_and_is_audited(client):
    await sync_master_admin(EMAIL, OLD)
    assert (await _login(client, EMAIL, OLD)).status_code == 200

    assert await sync_master_admin(EMAIL, NEW) == "updated"

    assert (await _login(client, EMAIL, OLD)).status_code == 401
    async with open_session() as db:
        live = (await db.execute(select(RefreshToken).where(RefreshToken.revoked_at.is_(None)))).scalars().all()
        entry = (await db.execute(
            select(AuditLog).where(AuditLog.action == "ADMIN_CREDENTIALS_SYNCED"))).scalar_one()
    assert live == []
    assert entry.event_metadata == {"changed": ["password"]}
    assert (await _login(client, EMAIL, NEW)).status_code == 200


async def test_email_change_moves_the_login(client):
    await sync_master_admin(EMAIL, OLD)
    assert await sync_master_admin("Renamed@VeriTrack.io ", OLD) == "updated"
    assert (await _login(client, EMAIL, OLD)).status_code == 401
    assert (await _login(client, "renamed@veritrack.io", OLD)).status_code == 200


async def test_refuses_an_email_owned_by_another_account(client):
    await sync_master_admin(EMAIL, OLD)
    headers = {"Authorization": f"Bearer {(await _login(client, EMAIL, OLD)).json()['access_token']}"}
    r = await client.post("/api/v1/users", headers=headers,
                          json={"email": "mgr@example.com", "role": "MANAGER", "full_name": "M"})
    assert r.status_code == 201, r.text
    with pytest.raises(SystemExit, match="already belongs"):
        await sync_master_admin("mgr@example.com", OLD)


def test_new_names_win_and_old_names_still_work(monkeypatch):
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "old@example.com")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "legacy")
    s = Settings()
    assert (s.admin_email, s.admin_password) == ("old@example.com", "legacy")
    monkeypatch.setenv("ADMIN_EMAIL", "new@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "current")
    s = Settings()
    assert (s.admin_email, s.admin_password) == ("new@example.com", "current")
