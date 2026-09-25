"""Regressions for defects found by the real-browser suite (e2e/)."""

import asyncio
import io
import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import func, select

from app.models.analysis import AnalysisRun, AnalysisStatus, GeneratedReport, ViolationResult
from tests.conftest import open_session
from tests.helpers import admin, create_user, csv_file, manager

REPO = "Employee ID,Full Name,Company Email\nE-1,Ann,ann@corp.io\nE-2,Bob,bob@corp.io\n"
GETS = "Employee ID,Name,Customer Leave,Company Leave\nE-1,Ann,x,\nE-2,Bob,x,x\n"


async def _analysed_batch(client, tag: str) -> tuple[dict, str]:
    h = await manager(client, tag)
    await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO", files=[csv_file("r.csv", REPO)], headers=h)
    batch = (await client.post("/api/v1/uploads?kind=GETS", files=[csv_file("g.csv", GETS)], headers=h)).json()
    r = await client.post(f"/api/v1/batches/{batch['id']}/analyze", headers=h)
    assert r.status_code == 202, r.text
    run_id = (await client.get(f"/api/v1/batches/{batch['id']}/analysis", headers=h)).json()["run_id"]
    return h, run_id


class TestReportsAfterResend:
    async def test_downloads_still_work_after_resend(self, client, ma_user_id):
        h, run_id = await _analysed_batch(client, "f.resend")
        for _ in range(2):
            assert (await client.post(f"/api/v1/runs/{run_id}/resend", headers=h)).status_code == 200
        for kind in ("summary.pdf", "3tab.xlsx"):
            r = await client.get(f"/api/v1/runs/{run_id}/reports/{kind}", headers=h)
            assert r.status_code == 200 and len(r.content) > 100, (kind, r.status_code)
        async with open_session() as db:
            n = (await db.execute(select(func.count()).select_from(GeneratedReport)
                                  .where(GeneratedReport.run_id == uuid.UUID(run_id)))).scalar_one()
        assert n == 2  # resend re-delivers, it does not duplicate reports


class TestDashboardScope:
    async def test_hr_sees_only_their_managers_numbers(self, client, ma_user_id):
        other = await manager(client, "f.other")
        await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO",
                          files=[csv_file("r.csv", REPO + "E-3,Cid,c@corp.io\n")], headers=other)
        h, _ = await _analysed_batch(client, "f.scope")
        _, hr = await create_user(client, h, "f.scope.hr@veritrack.io", "HR")
        body = (await client.get("/api/v1/dashboard/summary", headers=hr)).json()
        assert body["employees_total"] == 2
        assert body["batches_total"] == 2
        assert "violations_detected" not in body and "users_by_role" not in body

    async def test_executive_gets_accounts_by_role(self, client, ma_user_id):
        _, ex = await create_user(client, await admin(client), "f.exec@veritrack.io", "EXECUTIVE")
        body = (await client.get("/api/v1/dashboard/summary", headers=ex)).json()
        assert body["users_by_role"]["EXECUTIVE"] == 1


class TestNonTimesheetImage:
    async def test_noise_png_fails_with_reason(self, client, ma_user_id, monkeypatch):
        pytest.importorskip("rapidocr_onnxruntime")
        from app.core.config import settings
        from app.services.extraction.ocr import reset_ocr_engine_for_tests

        monkeypatch.setattr(settings, "ocr_engine", "rapid")
        reset_ocr_engine_for_tests()
        h = await manager(client, "f.noise")
        rng = np.random.default_rng(3)
        buf = io.BytesIO()
        Image.fromarray(rng.integers(0, 255, (300, 500, 3), dtype=np.uint8)).save(buf, "PNG")
        r = await client.post("/api/v1/uploads?kind=GETS",
                              files=[("files", ("noise.png", io.BytesIO(buf.getvalue()), "image/png"))],
                              headers=h)
        detail = (await client.get(f"/api/v1/uploads/batches/{r.json()['id']}", headers=h)).json()
        f = detail["files"][0]
        assert f["status"] == "FAILED" and not f["rows_extracted"]
        assert "No timesheet found" in f["error_message"]


class TestLeaveDelete:
    async def test_delete_returns_empty_204(self, client, ma_user_id):
        h = await manager(client, "f.leave")
        await client.post("/api/v1/leaves", json={"employee_code": "E-1", "start_date": "2026-07-01"}, headers=h)
        leave_id = (await client.get("/api/v1/leaves", headers=h)).json()["items"][0]["id"]
        r = await client.delete(f"/api/v1/leaves/{leave_id}", headers=h)
        assert r.status_code == 204 and r.content == b""
        assert "application/json" not in r.headers.get("content-type", "")


class TestAnalyzeClaim:
    async def test_concurrent_triggers_one_202_rest_409(self, client, ma_user_id, monkeypatch):
        from app.core.config import settings
        from app.services import jobs

        h = await manager(client, "f.claim")
        await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO", files=[csv_file("r.csv", REPO)], headers=h)
        batch = (await client.post("/api/v1/uploads?kind=GETS", files=[csv_file("g.csv", GETS)], headers=h)).json()
        monkeypatch.setattr(settings, "processing_mode", "background")
        codes = await asyncio.gather(*(
            client.post(f"/api/v1/batches/{batch['id']}/analyze", headers=h) for _ in range(4)
        ))
        await jobs.drain(10)
        assert sorted(r.status_code for r in codes) == [202, 409, 409, 409]
        res = (await client.get(f"/api/v1/batches/{batch['id']}/analysis", headers=h)).json()
        assert res["status"] == "COMPLETED" and res["totals"]["violations"] == 1

    async def test_running_state_visible_immediately(self, client, ma_user_id, monkeypatch):
        from app.core.config import settings
        from app.services import jobs

        h = await manager(client, "f.running")
        batch = (await client.post("/api/v1/uploads?kind=GETS", files=[csv_file("g.csv", GETS)], headers=h)).json()
        monkeypatch.setattr(settings, "processing_mode", "background")
        assert (await client.post(f"/api/v1/batches/{batch['id']}/analyze", headers=h)).status_code == 202
        first = await client.get(f"/api/v1/batches/{batch['id']}/analysis", headers=h)
        assert first.status_code == 200 and first.json()["status"] in ("RUNNING", "COMPLETED")
        await jobs.drain(10)

    async def test_interrupted_analysis_is_resumed_without_duplicates(self, client, ma_user_id, monkeypatch):
        from app.core.config import settings
        from app.services import jobs

        h, run_id = await _analysed_batch(client, "f.resume")
        async with open_session() as db:            # simulate a crash mid-analysis
            run = await db.get(AnalysisRun, uuid.UUID(run_id))
            run.status = AnalysisStatus.RUNNING
            run.started_at = datetime.now(UTC) - timedelta(hours=1)
            await db.commit()
        monkeypatch.setattr(settings, "processing_mode", "background")
        assert await jobs.recover_interrupted_analyses() == 1
        await jobs.drain(10)
        async with open_session() as db:
            run = await db.get(AnalysisRun, uuid.UUID(run_id))
            n = (await db.execute(select(func.count()).select_from(ViolationResult)
                                  .where(ViolationResult.run_id == run.id))).scalar_one()
        assert run.status is AnalysisStatus.COMPLETED and n == 1
