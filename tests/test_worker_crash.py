"""A worker killed in the middle of a job, or frozen and woken up after the job was taken over: the batch is
still finished, and every file's result is written exactly once.

Worker A is a real separate process (tests/crash_worker.py) that stops inside the reader on the second of
three files. The test kills it with SIGKILL, or freezes it with SIGSTOP; worker B is the reaper in this
process, which takes the batch over once A's lease runs out.
"""

import asyncio
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.core.config import settings
from app.models.uploads import BatchKind, BatchStatus, ExtractedRow, FileStatus, UploadBatch, UploadedFile
from app.models.user import User
from app.services import jobs
from app.services.batch_service import create_batch
from tests.conftest import open_session
from tests.helpers import manager

ROOT = Path(__file__).resolve().parents[1]
LEASE = 2
FILES = [(f"f{i}.csv", f"Employee ID,Full Name\nE-{i},Worker {i}\n".encode()) for i in (1, 2, 3)]

pytestmark = pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="needs POSIX signals")


@pytest.fixture
async def batch_id(client, ma_user_id, monkeypatch):
    monkeypatch.setattr(settings, "job_lease_seconds", LEASE)
    await manager(client, "crash")
    async with open_session() as db:
        owner = (await db.execute(select(User).where(User.email == "crash@veritrack.io"))).scalar_one()
        batch = await create_batch(db, manager=owner, kind=BatchKind.EMPLOYEE_REPO, files=FILES)
    return str(batch.id)


def _start_worker(batch: str, started: Path, pause: float) -> subprocess.Popen:
    env = {**os.environ, "PAUSE_ON": "E-2", "STARTED": str(started), "PAUSE_SECONDS": str(pause),
           "JOB_LEASE_SECONDS": str(LEASE)}
    return subprocess.Popen([sys.executable, "-m", "tests.crash_worker", batch], cwd=ROOT, env=env,  # noqa: S603
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


async def _wait_for(started: Path, worker: subprocess.Popen) -> None:
    for _ in range(300):
        if started.exists():
            return
        if worker.poll() is not None:
            pytest.fail(f"worker exited early:\n{worker.stdout.read() if worker.stdout else ''}")
        await asyncio.sleep(0.1)
    pytest.fail("worker never reached the second file")


async def _state(batch: str) -> dict:
    async with open_session() as db:
        b = await db.get(UploadBatch, batch, populate_existing=True)
        files = (await db.execute(select(UploadedFile).where(UploadedFile.batch_id == b.id)
                                  .order_by(UploadedFile.original_filename))).scalars().all()
        rows = dict((await db.execute(
            select(ExtractedRow.file_id, func.count()).join(UploadedFile).where(UploadedFile.batch_id == b.id)
            .group_by(ExtractedRow.file_id))).all())
        row_ids = dict((await db.execute(select(UploadedFile.original_filename, ExtractedRow.id).join(UploadedFile)
                                         .where(UploadedFile.batch_id == b.id))).all())
        return {"status": b.status, "attempts": b.attempts, "processed": b.processed_files,
                "failed": b.failed_files, "lease": b.lease_token,
                "files": [(f.original_filename, f.status, f.attempts, rows.get(f.id, 0)) for f in files],
                "row_ids": row_ids}


async def _until_lease_lapses(batch: str) -> None:
    for _ in range(100):
        async with open_session() as db:
            lapsed = (await db.execute(text(
                "SELECT lease_expires_at < now() FROM upload_batches WHERE id = :id"), {"id": batch})).scalar_one()
        if lapsed:
            return
        await asyncio.sleep(0.1)
    pytest.fail("the lease never ran out")


async def test_a_killed_worker_s_batch_is_finished_exactly_once_by_another(batch_id, tmp_path):
    started = tmp_path / "started"
    worker = _start_worker(batch_id, started, pause=60)
    await _wait_for(started, worker)
    worker.send_signal(signal.SIGKILL)
    worker.wait(10)

    # files run in no fixed order: f2 was in progress, each other file finished or not yet started
    mid = await _state(batch_id)
    assert mid["status"] is BatchStatus.PROCESSING
    by_name = {name: rest for name, *rest in mid["files"]}
    f2 = by_name.pop("f2.csv")
    assert f2 == [FileStatus.PROCESSING, 1, 0]
    assert all(rest in ([FileStatus.DONE, 1, 1], [FileStatus.QUEUED, 0, 0]) for rest in by_name.values())
    done_before = {name: mid["row_ids"][name] for name, rest in by_name.items() if rest[0] is FileStatus.DONE}

    assert await jobs.reap() == {"batches": 0, "files": 0}   # the lease is still live: hands off
    await _until_lease_lapses(batch_id)
    assert await jobs.reap() == {"batches": 1, "files": 0}   # inline mode: B finishes it here

    end = await _state(batch_id)
    assert end["status"] is BatchStatus.COMPLETED and end["attempts"] == 2 and end["lease"] is None
    assert (end["processed"], end["failed"]) == (3, 0)
    # f2 was taken over once, every file has exactly its one row, and files finished before the kill
    # were not redone (same attempt, same row)
    assert end["files"] == [("f1.csv", FileStatus.DONE, 1, 1), ("f2.csv", FileStatus.DONE, 2, 1),
                            ("f3.csv", FileStatus.DONE, 1, 1)]
    assert all(end["row_ids"][name] == row for name, row in done_before.items())
    async with open_session() as db:
        employees = (await db.execute(text("SELECT employee_code FROM employees ORDER BY 1"))).scalars().all()
    assert employees == ["E-1", "E-2", "E-3"]


async def test_a_frozen_worker_that_wakes_up_late_changes_nothing(batch_id, tmp_path):
    started = tmp_path / "started"
    worker = _start_worker(batch_id, started, pause=4)
    await _wait_for(started, worker)
    worker.send_signal(signal.SIGSTOP)
    frozen_at = time.monotonic()
    try:
        await _until_lease_lapses(batch_id)
        assert await jobs.reap() == {"batches": 1, "files": 0}
        finished = await _state(batch_id)
        assert finished["status"] is BatchStatus.COMPLETED
        await asyncio.sleep(max(0.0, 5 - (time.monotonic() - frozen_at)))   # its 4 s pause is over on waking
    finally:
        worker.send_signal(signal.SIGCONT)
    out, _ = worker.communicate(timeout=60)

    assert "file_result_discarded" in out and "lease_lost" in out, out
    assert await _state(batch_id) == finished   # not a row, status or counter changed
    assert finished["files"] == [("f1.csv", FileStatus.DONE, 1, 1), ("f2.csv", FileStatus.DONE, 2, 1),
                                 ("f3.csv", FileStatus.DONE, 1, 1)]


async def test_a_resumed_worker_s_result_writes_affect_zero_rows(batch_id, monkeypatch):
    """The result writes are single conditional UPDATEs on the lease token: once another worker has taken
    the job over, the old worker's own statements match no row."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from app.services.batch_service import fenced_batch_update
    from app.services.extraction.pipeline import _finish, claim_file

    async with open_session() as db:
        file_id = (await db.execute(select(UploadedFile.id).where(UploadedFile.batch_id == batch_id)
                                    .order_by(UploadedFile.original_filename).limit(1))).scalar_one()
        token_a = await claim_file(db, file_id)                       # worker A claims, then freezes
        stale_batch_token = (await db.execute(update(UploadBatch).where(UploadBatch.id == batch_id)
                             .values(status=BatchStatus.PROCESSING, lease_token=func.gen_random_uuid())
                             .returning(UploadBatch.lease_token))).scalar_one()
        await db.execute(update(UploadedFile).where(UploadedFile.id == file_id)   # A's lease runs out
                         .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await db.commit()
        token_b = await claim_file(db, file_id)                       # worker B takes over
        assert token_a and token_b and token_a != token_b
        await db.execute(update(UploadBatch).where(UploadBatch.id == batch_id)
                         .values(lease_token=func.gen_random_uuid()))   # and the batch
        await db.commit()

        before = await _state(batch_id)
        # rows each statement changed (RETURNING lists them)
        a_file = (await db.execute(_finish(file_id, token_a, status=FileStatus.DONE, rows_extracted=99))).all()
        a_batch = (await db.execute(fenced_batch_update(uuid.UUID(batch_id), stale_batch_token,
                                                        status=BatchStatus.COMPLETED, processed_files=99))).all()
        assert (len(a_file), len(a_batch)) == (0, 0)
        await db.commit()
        assert await _state(batch_id) == before

        # the holder's token is what makes the difference
        b_file = (await db.execute(_finish(file_id, token_b, status=FileStatus.DONE, rows_extracted=1))).all()
        assert len(b_file) == 1
        await db.rollback()

