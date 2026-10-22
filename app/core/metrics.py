"""Prometheus metrics for the OCR queue, served at GET /metrics (only when METRICS_TOKEN is set).

Two kinds:
- what this process did since it started: files finished by outcome, claims and takeovers, processing time
  and queue wait (counters and histograms, per process);
- the state of the queue right now, read from the database at scrape time, so every replica reports the same
  numbers: files waiting or in progress, the age of the oldest waiting file, and leases that ran out without
  being taken over yet (a sign that no worker or reaper is running).
"""

from fastapi import APIRouter, Header, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import constant_time_equals

FILES_FINISHED = Counter("veritrack_ocr_files_total", "Files finished, by outcome", ["outcome"])
CLAIMS = Counter("veritrack_job_claims_total", "Jobs claimed; takeover = a dead worker's job claimed again",
                 ["job", "takeover"])
FILE_SECONDS = Histogram("veritrack_ocr_file_seconds", "Time from claiming a file to writing its outcome",
                         buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300))
QUEUE_WAIT_SECONDS = Histogram("veritrack_ocr_queue_wait_seconds", "Time from upload to a file's first claim",
                               buckets=(0.1, 0.5, 1, 5, 15, 30, 60, 120, 300, 900))

QUEUE_FILES = Gauge("veritrack_ocr_queue_files", "Files by state, all organisations", ["status"])
OLDEST_WAITING = Gauge("veritrack_ocr_oldest_waiting_seconds", "Age of the oldest file waiting to be claimed")
LAPSED_LEASES = Gauge("veritrack_job_leases_lapsed", "Jobs in progress whose lease ran out", ["job"])

router = APIRouter()


async def _read_queue() -> None:
    from app.db.session import get_session_factory
    from app.db.tenant import SYSTEM, tenant
    from app.models.uploads import FileStatus, UploadBatch, UploadedFile
    from app.services import leases

    with tenant(SYSTEM):  # counts only, across organisations
        async with get_session_factory()() as db:
            counts = dict((await db.execute(
                select(UploadedFile.status, func.count())
                .where(UploadedFile.status.in_([FileStatus.QUEUED, FileStatus.PROCESSING, FileStatus.PENDING_OCR]))
                .group_by(UploadedFile.status))).all())
            oldest = (await db.execute(
                select(func.extract("epoch", func.now() - func.min(UploadedFile.created_at)))
                .where(UploadedFile.status == FileStatus.QUEUED))).scalar_one()
            for job, model in (("batch", UploadBatch), ("file", UploadedFile)):
                LAPSED_LEASES.labels(job).set(
                    (await db.execute(select(func.count()).where(leases.lapsed(model)))).scalar_one())
    for status in (FileStatus.QUEUED, FileStatus.PROCESSING, FileStatus.PENDING_OCR):
        QUEUE_FILES.labels(status.value).set(counts.get(status, 0))
    OLDEST_WAITING.set(float(oldest or 0))


@router.get("/metrics", include_in_schema=False)
async def metrics(authorization: str | None = Header(default=None)) -> Response:
    if not settings.metrics_token:
        raise HTTPException(404, detail={"code": "not_found", "message": "Not found"})
    if not authorization or not constant_time_equals(authorization, f"Bearer {settings.metrics_token}"):
        raise HTTPException(401, detail={"code": "unauthorized", "message": "Metrics token required"})
    await _read_queue()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
