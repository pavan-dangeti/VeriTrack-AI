"""Observability, rate limiting, and retention hardening.

Covers: error envelope shape + request-id echo, /health/ready probes,
per-user rate limits on expensive endpoints, retention purge semantics,
and the soft-delete guarantee on employee records.
"""

import io
import uuid
from datetime import UTC, datetime, timedelta

from tests.conftest import MA_EMAIL, MA_PASSWORD, test_session

REPO_CSV = b"Employee ID,Full Name\nE-100,Ann Weaver\n"


async def _login(client, email, password):
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _make_manager(client, ma_headers, label="ops"):
    r = await client.post(
        "/api/v1/users", json={"email": f"{label}.mgr@veritrack.io", "role": "MANAGER"},
        headers=ma_headers,
    )
    assert r.status_code == 201, r.text
    return await _login(client, f"{label}.mgr@veritrack.io", r.json()["initial_password"])


class TestErrorEnvelopeAndRequestId:
    async def test_error_envelope_shape_and_request_id_echo(self, client, ma_user_id):
        rid = "c1e7b4a3f2d94865"  # 16 hex chars — passes the middleware sanity check
        r = await client.get(
            f"/api/v1/employees/{uuid.uuid4()}/detail",
            headers={"X-Request-ID": rid},  # no auth token -> 401 envelope
        )
        assert r.status_code == 401
        body = r.json()
        assert set(body["error"]) >= {"code", "message", "request_id"}
        assert body["error"]["request_id"] == rid
        assert r.headers["x-request-id"] == rid

    async def test_server_generates_request_id_when_absent(self, client):
        r = await client.get("/health")
        assert r.status_code == 200
        generated = r.headers["x-request-id"]
        assert generated and len(generated) <= 64

    async def test_unmapped_path_404_keeps_envelope(self, client):
        r = await client.get("/api/v1/definitely-not-a-route")
        assert r.status_code == 404
        assert "error" in r.json()


class TestReadiness:
    async def test_health_ready_probes_dependencies(self, client):
        r = await client.get("/health/ready")
        assert r.status_code in (200, 503)
        checks = r.json()["checks"]
        assert checks["db"] is True  # postgres is up in the test env
        assert isinstance(checks["redis"], bool)  # redis may be absent locally -> 503


class TestRateLimiting:
    async def test_uploads_rate_limited_for_one_user(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        mgr = await _make_manager(client, ma, "rl")

        statuses = []
        for i in range(12):
            r = await client.post(
                "/api/v1/uploads?kind=EMPLOYEE_REPO",
                files=[("files", (f"r{i}.csv", io.BytesIO(REPO_CSV), "text/csv"))],
                headers=mgr,
            )
            statuses.append(r.status_code)
        assert statuses[:10] == [201] * 10
        assert statuses[10:] == [429, 429], statuses
        assert statuses.count(201) == 10


class TestRetentionAndSoftDelete:
    async def test_purge_removes_only_old_batches(self, client, ma_user_id):
        from sqlalchemy import select
        from sqlalchemy import update as sa_update

        from app.models.uploads import UploadBatch

        ma = await _login(client, MA_EMAIL, MA_PASSWORD)

        # MA needs a manager to own batches — create one, upload, then age one batch
        mgr_headers = await _make_manager(client, ma, "purge")
        for i in range(2):
            r = await client.post(
                "/api/v1/uploads?kind=EMPLOYEE_REPO",
                files=[("files", (f"p{i}.csv", io.BytesIO(REPO_CSV), "text/csv"))],
                headers=mgr_headers,
            )
            assert r.status_code == 201
        async with test_session() as db:
            batches = (await db.execute(select(UploadBatch))).scalars().all()
            assert len(batches) == 2
            old_id, new_id = batches[0].id, batches[1].id
            await db.execute(
                sa_update(UploadBatch)
                .where(UploadBatch.id == old_id)
                .values(created_at=datetime.now(UTC) - timedelta(days=1000))
            )
            await db.commit()

        r = await client.post("/api/v1/settings/purge-obsolete-data", headers=ma)
        assert r.status_code == 200, r.text
        assert r.json()["purged_batches"] == 1

        async with test_session() as db:
            remaining = set(await db.scalars(select(UploadBatch.id)))
            assert remaining == {new_id}

    async def test_employees_survive_purge_and_have_no_hard_delete(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        mgr = await _make_manager(client, ma, "keep")
        await client.post(
            "/api/v1/uploads?kind=EMPLOYEE_REPO",
            files=[("files", ("k.csv", io.BytesIO(REPO_CSV), "text/csv"))],
            headers=mgr,
        )
        listing = (await client.get("/api/v1/employees", headers=mgr)).json()
        emp_id = listing["items"][0]["id"]

        # No hard-delete route exists at all — the model only supports is_deleted.
        r = await client.request("DELETE", f"/api/v1/employees/{emp_id}", headers=mgr)
        assert r.status_code == 405

        # Purge still hasn't touched employees
        await client.post("/api/v1/settings/purge-obsolete-data", headers=ma)
        after = (await client.get("/api/v1/employees", headers=mgr)).json()
        assert after["total"] == 1
