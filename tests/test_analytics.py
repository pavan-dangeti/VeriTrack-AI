"""Analytics aggregation endpoint: content, scoping, and access control."""

import uuid
from datetime import UTC, datetime

from tests.conftest import MA_EMAIL, MA_PASSWORD, test_session


async def _login(client, email, password):
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _create(client, headers, email, role, full_name=None):
    r = await client.post(
        "/api/v1/users", json={"email": email, "role": role, "full_name": full_name},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _seed_runs(manager_id):
    """Two completed runs for the manager in two different months + one batch each."""
    from app.models.analysis import AnalysisRun, AnalysisStatus
    from app.models.uploads import BatchKind, BatchStatus, UploadBatch

    async with test_session() as db:
        for i, (month, viol, rows, matched) in enumerate(
            [(5, 7, 20, 13), (6, 3, 10, 9)]
        ):
            batch = UploadBatch(
                manager_id=manager_id, kind=BatchKind.GETS, status=BatchStatus.COMPLETED,
                total_files=2 + i, processed_files=2 + i, failed_files=0,
                created_at=datetime(2026, month, 10, tzinfo=UTC),
            )
            db.add(batch)
            await db.flush()
            db.add(
                AnalysisRun(
                    batch_id=batch.id, manager_id=manager_id,
                    status=AnalysisStatus.COMPLETED,
                    files_processed=2 + i, rows_processed=rows, matched=matched,
                    violations=viol, emails_sent=viol - 1, emails_missing=1,
                    emails_errored=0, skipped=i,
                    started_at=datetime(2026, month, 15, tzinfo=UTC),
                    completed_at=datetime(2026, month, 15, tzinfo=UTC),
                )
            )
        await db.commit()


class TestAnalyticsSummary:
    async def test_master_admin_sees_all_managers_with_aggregation(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        a = await _create(client, ma, "an.a@veritrack.io", "MANAGER", full_name="Ann Manager")
        b = await _create(client, ma, "an.b@veritrack.io", "MANAGER")
        await _seed_runs(uuid.UUID(a["user"]["id"]))
        await _seed_runs(uuid.UUID(b["user"]["id"]))

        r = await client.get("/api/v1/analytics/summary", headers=ma)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["scoped_to_self"] is False
        months = {m["month"]: m for m in body["monthly"]}
        assert months["2026-05"]["violations"] == 14  # 7 + 7 across both managers
        assert months["2026-06"]["matched"] == 18
        assert months["2026-05"]["batches"] == 2
        assert body["emails"] == {"sent": 16, "missing": 4, "errored": 0, "skipped": 2}
        names = {m["manager_name"] for m in body["by_manager"]}
        assert "Ann Manager" in names  # full_name preferred in the breakdown
        assert "an.b@veritrack.io" in names  # email fallback when no name

    async def test_manager_scoped_to_own_workspace(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        a = await _create(client, ma, "sc.a@veritrack.io", "MANAGER")
        b = await _create(client, ma, "sc.b@veritrack.io", "MANAGER")
        await _seed_runs(uuid.UUID(a["user"]["id"]))
        mgr_a = await _login(client, "sc.a@veritrack.io", a["initial_password"])

        r = await client.get("/api/v1/analytics/summary", headers=mgr_a)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["scoped_to_self"] is True
        assert "by_manager" not in body
        total_violations = sum(m["violations"] for m in body["monthly"])
        assert total_violations == 10  # only their own 7 + 3, none of B's

    async def test_hr_scoped_to_own_manager(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        a = await _create(client, ma, "an.hr.mgr@veritrack.io", "MANAGER")
        b = await _create(client, ma, "an.hr.mgr2@veritrack.io", "MANAGER")
        mgr = await _login(client, "an.hr.mgr@veritrack.io", a["initial_password"])
        created = await client.post(
            "/api/v1/users", json={"email": "an.hr@veritrack.io", "role": "HR"}, headers=mgr
        )
        hr = await _login(client, "an.hr@veritrack.io", created.json()["initial_password"])

        await _seed_runs(uuid.UUID(a["user"]["id"]))
        await _seed_runs(uuid.UUID(b["user"]["id"]))

        r = await client.get("/api/v1/analytics/summary", headers=hr)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["scoped_to_self"] is True
        assert "by_manager" not in body
        total = sum(m["violations"] for m in body["monthly"])
        assert total == 10  # only their manager A's violations, none of B's

    async def test_empty_state_zeroes(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        r = await client.get("/api/v1/analytics/summary", headers=ma)
        assert r.status_code == 200
        body = r.json()
        assert body["monthly"] == []
        assert body["emails"] == {"sent": 0, "missing": 0, "errored": 0, "skipped": 0}
