"""GET /metrics: off without a token, refused with a wrong one, and its numbers follow the queue."""

import uuid
from datetime import UTC, datetime, timedelta

from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy import select

from app.core.config import settings
from app.models.uploads import BatchKind, BatchStatus, FileStatus, UploadBatch, UploadedFile
from app.models.user import User
from app.services import jobs
from app.services.batch_service import create_batch
from tests.conftest import open_session
from tests.helpers import manager

TOKEN = "metrics-test-token"


async def _scrape(client) -> dict:
    r = await client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200, r.text
    return {(s.name, tuple(sorted(s.labels.items()))): s.value
            for family in text_string_to_metric_families(r.text) for s in family.samples}


def _value(samples: dict, name: str, **labels) -> float:
    return samples.get((name, tuple(sorted(labels.items()))), 0.0)


async def test_metrics_need_a_configured_token(client, monkeypatch):
    assert (await client.get("/metrics")).status_code == 404     # not configured: does not exist
    monkeypatch.setattr(settings, "metrics_token", TOKEN)
    assert (await client.get("/metrics")).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})).status_code == 200


async def test_metrics_follow_the_queue(client, ma_user_id, monkeypatch):
    monkeypatch.setattr(settings, "metrics_token", TOKEN)
    await manager(client, "metrics")
    async with open_session() as db:
        owner = (await db.execute(select(User).where(User.email == "metrics@veritrack.io"))).scalar_one()
        waiting = await create_batch(db, manager=owner, kind=BatchKind.EMPLOYEE_REPO,
                                     files=[("w.csv", b"Employee ID,Full Name\nM-1,Waiting\n")])
        abandoned = await create_batch(db, manager=owner, kind=BatchKind.EMPLOYEE_REPO,
                                       files=[("a.csv", b"Employee ID,Full Name\nM-2,Abandoned\n")])
        b = await db.get(UploadBatch, abandoned.id)   # its worker died: the lease ran out
        b.status, b.lease_token, b.attempts = BatchStatus.PROCESSING, uuid.uuid4(), 1
        b.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        f = (await db.execute(select(UploadedFile).where(UploadedFile.batch_id == abandoned.id))).scalar_one()
        f.status = FileStatus.PROCESSING
        f.lease_token, f.lease_expires_at, f.attempts = uuid.uuid4(), b.lease_expires_at, 1
        await db.commit()

    before = await _scrape(client)
    assert _value(before, "veritrack_ocr_queue_files", status="QUEUED") == 1
    assert _value(before, "veritrack_ocr_queue_files", status="PROCESSING") == 1
    assert _value(before, "veritrack_ocr_oldest_waiting_seconds") > 0
    assert _value(before, "veritrack_job_leases_lapsed", job="batch") == 1
    assert _value(before, "veritrack_job_leases_lapsed", job="file") == 1

    assert await jobs.reap() == {"batches": 1, "files": 0}   # inline mode: taken over and finished here
    await jobs.dispatch_batch(str(waiting.id))

    after = await _scrape(client)
    assert _value(after, "veritrack_ocr_queue_files", status="QUEUED") == 0
    assert _value(after, "veritrack_ocr_queue_files", status="PROCESSING") == 0
    assert _value(after, "veritrack_job_leases_lapsed", job="batch") == 0
    assert _value(after, "veritrack_ocr_oldest_waiting_seconds") == 0

    def grew(name, **labels):
        return _value(after, name, **labels) - _value(before, name, **labels)

    assert grew("veritrack_ocr_files_total", outcome="done") == 2
    assert grew("veritrack_job_claims_total", job="batch", takeover="true") == 1
    assert grew("veritrack_job_claims_total", job="file", takeover="true") == 1
    assert grew("veritrack_job_claims_total", job="file", takeover="false") == 1
    assert grew("veritrack_ocr_file_seconds_count") == 2
    assert grew("veritrack_ocr_queue_wait_seconds_count") == 1   # only the file that came off the queue
