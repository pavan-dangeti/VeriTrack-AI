"""Multi-user safety: atomic claims, race-free analysis, background jobs."""

import asyncio
import uuid

from sqlalchemy import func, select

from app.models.analysis import AnalysisRun
from app.models.uploads import ExtractedRow, FileStatus, UploadedFile
from tests.conftest import open_session
from tests.helpers import csv_file, manager

REPO = "Employee ID,Full Name\nE-1,Ann\nE-2,Bob\nE-3,Cid\n"
GETS = "Employee ID,Name,Customer Leave,Company Leave\nE-1,Ann,x,\nE-2,Bob,x,x\n"


async def _file_id(client, h, batch_id) -> uuid.UUID:
    detail = (await client.get(f"/api/v1/uploads/batches/{batch_id}", headers=h)).json()
    return uuid.UUID(detail["files"][0]["id"])


class TestAtomicClaims:
    async def test_same_file_processed_concurrently_is_extracted_once(self, client, ma_user_id):
        from app.services.extraction.pipeline import process_uploaded_file

        h = await manager(client, "cc.claim")
        batch = (await client.post("/api/v1/uploads?kind=GETS", files=[csv_file("g.csv", GETS)], headers=h)).json()
        fid = await _file_id(client, h, batch["id"])
        async with open_session() as db:           # reset to a claimable state
            f = await db.get(UploadedFile, fid)
            f.status = FileStatus.FAILED
            await db.execute(ExtractedRow.__table__.delete().where(ExtractedRow.file_id == fid))
            await db.commit()

        async def run():
            async with open_session() as db:
                return await process_uploaded_file(db, fid)

        results = await asyncio.gather(*(run() for _ in range(5)))
        assert results.count(True) == 1
        async with open_session() as db:
            count = await db.scalar(select(func.count()).where(ExtractedRow.file_id == fid))
        assert count == 2                          # rows inserted once, not 5×

    async def test_batch_runner_is_idempotent(self, client, ma_user_id):
        from app.services.batch_service import run_batch_processing

        h = await manager(client, "cc.batch")
        batch = (await client.post("/api/v1/uploads?kind=GETS", files=[csv_file("g.csv", GETS)], headers=h)).json()
        async with open_session() as db:
            assert (await run_batch_processing(db, batch["id"])) == {"status": "skipped"}

    async def test_concurrent_analyze_triggers_create_one_run(self, client, ma_user_id):
        from app.services.analyze_service import AnalyzeRuleError, execute_analysis

        h = await manager(client, "cc.analyze")
        await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO", files=[csv_file("r.csv", REPO)], headers=h)
        batch = (await client.post("/api/v1/uploads?kind=GETS", files=[csv_file("g.csv", GETS)], headers=h)).json()

        async def run():
            async with open_session() as db:
                try:
                    return await execute_analysis(db, batch["id"])
                except AnalyzeRuleError as exc:
                    return exc.status_code

        outcomes = await asyncio.gather(*(run() for _ in range(4)))
        assert sum(isinstance(o, dict) for o in outcomes) == 1
        assert all(o == 409 for o in outcomes if not isinstance(o, dict))
        async with open_session() as db:
            runs = await db.scalar(select(func.count()).select_from(AnalysisRun))
        assert runs == 1

    async def test_force_reprocess_while_processing_is_rejected(self, client, ma_user_id):
        h = await manager(client, "cc.busy")
        batch = (await client.post("/api/v1/uploads?kind=GETS", files=[csv_file("g.csv", GETS)], headers=h)).json()
        fid = await _file_id(client, h, batch["id"])
        async with open_session() as db:
            (await db.get(UploadedFile, fid)).status = FileStatus.PROCESSING
            await db.commit()
        r = await client.post(f"/api/v1/uploads/batches/{batch['id']}/files/{fid}/reprocess?force=true", headers=h)
        assert r.status_code == 409 and r.json()["error"]["code"] == "busy"


class TestBackgroundMode:
    async def test_upload_returns_immediately_and_completes_in_background(self, client, ma_user_id, monkeypatch):
        from app.core.config import settings

        h = await manager(client, "bg.mode")
        monkeypatch.setattr(settings, "processing_mode", "background")
        r = await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO", files=[csv_file("r.csv", REPO)], headers=h)
        assert r.status_code == 201 and r.json()["status"] in ("QUEUED", "PROCESSING", "COMPLETED")
        for _ in range(100):
            status = (await client.get(f"/api/v1/uploads/batches/{r.json()['id']}", headers=h)).json()["status"]
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)
        assert status == "COMPLETED"
        assert (await client.get("/api/v1/employees", headers=h)).json()["total"] == 3

    async def test_analysis_in_background_reports_running_then_result(self, client, ma_user_id, monkeypatch):
        from app.core.config import settings

        h = await manager(client, "bg.analysis")
        await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO", files=[csv_file("r.csv", REPO)], headers=h)
        batch = (await client.post("/api/v1/uploads?kind=GETS", files=[csv_file("g.csv", GETS)], headers=h)).json()
        monkeypatch.setattr(settings, "processing_mode", "background")
        r = await client.post(f"/api/v1/batches/{batch['id']}/analyze", headers=h)
        assert r.status_code == 202 and r.json()["status"] == "RUNNING"
        for _ in range(100):
            res = await client.get(f"/api/v1/batches/{batch['id']}/analysis", headers=h)
            if res.status_code == 200 and res.json()["status"] == "COMPLETED":
                break
            await asyncio.sleep(0.05)
        assert res.json()["totals"]["violations"] == 1

    async def test_interrupted_batches_are_recovered(self, client, ma_user_id, monkeypatch):
        from datetime import UTC, datetime, timedelta

        from app.core.config import settings
        from app.models.uploads import BatchStatus, UploadBatch
        from app.services import jobs

        h = await manager(client, "bg.recover")
        batch = (await client.post("/api/v1/uploads?kind=GETS", files=[csv_file("g.csv", GETS)], headers=h)).json()
        async with open_session() as db:           # simulate a crash mid-batch
            b = await db.get(UploadBatch, uuid.UUID(batch["id"]))
            b.status = BatchStatus.PROCESSING
            b.created_at = datetime.now(UTC) - timedelta(hours=1)
            f = (await db.execute(select(UploadedFile).where(UploadedFile.batch_id == b.id))).scalar_one()
            f.status = FileStatus.PROCESSING
            await db.execute(ExtractedRow.__table__.delete().where(ExtractedRow.file_id == f.id))
            await db.commit()
        monkeypatch.setattr(settings, "processing_mode", "background")
        assert await jobs.recover_interrupted_batches() == 1
        await jobs.drain(10)
        detail = (await client.get(f"/api/v1/uploads/batches/{batch['id']}", headers=h)).json()
        assert detail["status"] == "COMPLETED" and detail["files"][0]["status"] == "DONE"
