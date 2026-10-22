"""Per-file extraction orchestrator.

OCR runs on a dedicated thread pool (OCR_CONCURRENCY) so screenshots never starve the shared pool,
and no DB connection is held during OCR. Claiming a file takes a lease on it (app/services/leases.py): the
outcome is written only while the lease is held, so it is written exactly once.
"""

import asyncio
import os
import threading
import time
import uuid as uuid_mod
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy import case, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.config import settings
from app.core.logging import get_logger
from app.models.uploads import ExtractedRow, FileStatus, UploadBatch, UploadedFile
from app.services import leases
from app.services.extraction import readers
from app.services.extraction.llm_verify import verify_row
from app.services.extraction.normalize import normalize_tables
from app.services.extraction.ocr import OcrUnavailableError

log = get_logger("extraction")

CLAIMABLE = (FileStatus.QUEUED, FileStatus.PENDING_OCR, FileStatus.FAILED)


class NoRowsError(ValueError):
    pass


_ocr_pool: ThreadPoolExecutor | None = None
_ocr_pool_lock = threading.Lock()


def _lower_priority() -> None:
    """OCR yields the CPU to request handling when the machine is saturated."""
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
    except (AttributeError, OSError):
        pass


def _executor_for(content_type: str) -> ThreadPoolExecutor | None:
    global _ocr_pool
    if not (content_type.startswith("image/") or content_type == "application/pdf"):
        return None
    with _ocr_pool_lock:
        if _ocr_pool is None:
            _ocr_pool = ThreadPoolExecutor(
                max(1, settings.ocr_concurrency), thread_name_prefix="ocr", initializer=_lower_priority
            )
    return _ocr_pool


def _extract(content_type: str, data: bytes, kind: str | None = None):
    tables = readers.read_any(content_type, data)
    rows = [verify_row(r) for r in normalize_tables(tables, kind=kind)]
    meta: dict = {}
    for table in tables:
        sheet = (getattr(table, "meta", None) or {}).get("sheet")
        if sheet:
            meta.setdefault("sheets", []).append(sheet)
    return rows, meta


async def claim_file(db: AsyncSession, file_id: uuid_mod.UUID) -> uuid_mod.UUID | None:
    """Takes a lease on the file and returns its token, or None when the file is done or held by a live
    worker. A file whose worker died on it is claimable again once the lease runs out, up to
    JOB_MAX_ATTEMPTS times in a row; after that it is failed, so one file that crashes the reader cannot
    stall its batch forever."""
    token = uuid_mod.uuid4()
    interrupted = UploadedFile.status == FileStatus.PROCESSING
    attempts = (await db.execute(
        update(UploadedFile)
        .where(UploadedFile.id == file_id,
               or_(UploadedFile.status.in_(CLAIMABLE),
                   leases.lapsed(UploadedFile) & (UploadedFile.attempts < settings.job_max_attempts)))
        .values(status=FileStatus.PROCESSING, error_message=None, lease_token=token,
                lease_expires_at=leases.new_expiry(), started_at=func.now(),
                attempts=case((interrupted, UploadedFile.attempts + 1), else_=1))
        .returning(UploadedFile.attempts)
    )).scalar_one_or_none()
    if attempts is None:
        given_up = (await db.execute(
            update(UploadedFile)
            .where(UploadedFile.id == file_id, leases.lapsed(UploadedFile),
                   UploadedFile.attempts >= settings.job_max_attempts)
            .values(status=FileStatus.FAILED, lease_token=None, lease_expires_at=None, processed_at=func.now(),
                    error_message=f"Processing was interrupted {settings.job_max_attempts} times; "
                                  "reprocess the file to try again")
            .returning(UploadedFile.id)
        )).scalar_one_or_none()
        if given_up:
            log.warning("file_given_up", file_id=str(file_id), attempts=settings.job_max_attempts)
    await db.commit()
    if attempts is not None:
        metrics.CLAIMS.labels("file", str(attempts > 1).lower()).inc()
        log.info("file_claimed", file_id=str(file_id), attempt=attempts, worker=leases.WORKER)
    return token if attempts is not None else None


def _finish(file_id: uuid_mod.UUID, token: uuid_mod.UUID, **values):
    """The file's outcome, written only while this claim still holds the lease."""
    return (
        update(UploadedFile)
        .where(UploadedFile.id == file_id, UploadedFile.lease_token == token,
               UploadedFile.status == FileStatus.PROCESSING)
        .values(**values, processed_at=func.now(), lease_token=None, lease_expires_at=None)
        .returning(UploadedFile.id)
    )


async def process_uploaded_file(db: AsyncSession, file_id: uuid_mod.UUID) -> bool:
    token = await claim_file(db, file_id)
    if token is None:
        return False  # done, or a live worker has it
    file = await db.get(UploadedFile, file_id, populate_existing=True)
    if file is None:
        return False
    started = time.monotonic()
    context = {"file_id": str(file_id), "batch_id": str(file.batch_id), "attempt": file.attempts}
    if file.attempts == 1 and file.processed_at is None:   # its first run, straight from the queue
        metrics.QUEUE_WAIT_SECONDS.observe((datetime.now(UTC) - file.created_at).total_seconds())

    def finished(outcome: str) -> float:
        seconds = time.monotonic() - started
        metrics.FILES_FINISHED.labels(outcome).inc()
        if outcome != "discarded":
            metrics.FILE_SECONDS.observe(seconds)
        return round(seconds * 1000)

    try:
        from app.services.storage import get_storage

        batch = await db.get(UploadBatch, file.batch_id)
        kind = batch.kind.value if batch else None
        content_type = file.content_type_detected or ""
        await db.commit()  # release the connection before the slow part

        async with leases.kept(db, UploadedFile, file_id, token):
            data = await asyncio.to_thread(get_storage().get_bytes, file.storage_key)
            rows, meta = await asyncio.get_running_loop().run_in_executor(
                _executor_for(content_type), _extract, content_type, data, kind
            )
        if not rows:
            raise NoRowsError(
                "No timesheet found in this file" if kind == "TIMESHEET" else "No data rows found in this file"
            )

        written = (await db.execute(_finish(file_id, token, status=FileStatus.DONE, rows_extracted=len(rows),
                                            extraction_meta=meta or None))).scalar_one_or_none()
        if written is None:
            await db.rollback()
            log.warning("file_result_discarded", **context, duration_ms=finished("discarded"),
                        reason="lease taken over or file gone")
            return False
        db.add_all(
            ExtractedRow(
                file_id=file_id,
                row_index=idx,
                data=row.values,
                confidence=row.confidence,
                needs_review=row.needs_review,
                review_note=row.review_note,
            )
            for idx, row in enumerate(rows)
        )
        await db.commit()
        log.info("file_processed", **context, rows=len(rows), duration_ms=finished("done"))
        return True

    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        if isinstance(exc, OcrUnavailableError):
            # Engine missing, not a bad file: keep it retryable.
            status, error = FileStatus.PENDING_OCR, str(exc)[:300]
        else:
            status = FileStatus.FAILED
            error = str(exc) if isinstance(exc, NoRowsError) else f"{type(exc).__name__}: {str(exc)[:300]}"
        written = (await db.execute(_finish(file_id, token, status=status, error_message=error))).scalar_one_or_none()
        await db.commit()
        if written is None:
            log.warning("file_result_discarded", **context, duration_ms=finished("discarded"),
                        reason="lease taken over or file gone")
            return False
        log.warning("file_not_processed", **context, status=status.value, error=error,
                    duration_ms=finished(status.value.lower()))
        return False
