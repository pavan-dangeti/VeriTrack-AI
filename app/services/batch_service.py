import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.config import settings
from app.core.logging import get_logger
from app.models.uploads import (
    BatchKind,
    BatchStatus,
    FileStatus,
    UploadBatch,
    UploadedFile,
)
from app.models.user import User
from app.services import audit_service
from app.services.file_validation import FileValidationError
from app.services.storage import build_key, get_storage

log = get_logger("uploads")

ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv", ".png", ".jpg", ".jpeg"}


class UploadRuleError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


async def create_batch(
    db: AsyncSession,
    *,
    manager: User,
    kind: BatchKind,
    files: list[tuple[str, bytes]],  # (filename, content)
) -> UploadBatch:
    if not files:
        raise UploadRuleError(400, "no_files", "No files provided")
    if len(files) > settings_max_files():
        raise UploadRuleError(
            400,
            "too_many_files",
            f"Maximum {settings_max_files()} files per batch",
        )

    # Validate every file BEFORE creating anything: a batch is all-or-nothing,
    # so a rejected file can never leave a half-created batch behind.
    from app.services.file_validation import sniff_content_type

    accepted: list[tuple[str, bytes, str]] = []
    for filename, content in files:
        if not any(filename.lower().endswith(e) for e in ALLOWED_EXTENSIONS):
            raise UploadRuleError(
                400,
                "bad_extension",
                f"'{filename}': allowed types are PDF/XLSX/XLS/CSV/PNG/JPG/JPEG",
            )
        if len(content) == 0:
            raise UploadRuleError(400, "empty_file", f"'{filename}' is empty")
        if len(content) > _max_file_bytes():
            raise UploadRuleError(
                413,
                "file_too_large",
                f"'{filename}' exceeds the {_max_file_mb()}MB limit",
            )
        try:
            detected = sniff_content_type(content, filename)
        except FileValidationError as exc:
            await audit_service.record(
                db,
                action="UPLOAD_REJECTED",
                result=audit_service.AuditResult.FAILURE,
                actor_user_id=manager.id,
                target_entity="file",
                target_id=filename[:100],
                metadata={"reason": exc.code},
            )
            raise UploadRuleError(415, exc.code, f"'{filename}': {exc.message}") from exc
        accepted.append((filename, content, detected))

    storage = get_storage()
    batch = UploadBatch(manager_id=manager.id, kind=kind, total_files=len(files))
    db.add(batch)
    await db.flush()

    import io

    for filename, content, detected in accepted:
        key = build_key(
            manager_id=str(manager.id), kind=kind.value, batch_id=str(batch.id),
            filename=filename,
        )
        stored = await asyncio.to_thread(storage.put, key, io.BytesIO(content), len(content))
        db.add(
            UploadedFile(
                batch_id=batch.id,
                manager_id=manager.id,
                original_filename=filename,
                storage_key=stored.key,
                content_type_detected=detected,
                file_size=stored.size,
                checksum_sha256=stored.checksum_sha256,
            )
        )

    await audit_service.record(
        db,
        action="CREATE_UPLOAD_BATCH",
        result=audit_service.AuditResult.SUCCESS,
        actor_user_id=manager.id,
        target_entity="batch",
        target_id=str(batch.id),
        metadata={"kind": kind.value, "files": len(files)},
    )
    return batch


async def run_batch_processing(db: AsyncSession, batch_id: str) -> dict:
    """Processes a batch's files one at a time (bounded memory, fair to other managers' batches).

    The batch is claimed with a lease that is renewed while it runs (app/services/leases.py). If the worker
    dies, the next one claims the batch once the lease runs out and skips the files already done; progress and
    the result are written only while the lease is held, so a batch is finished exactly once."""
    from sqlalchemy import func, or_, update

    from app.services import leases

    bid = uuid.UUID(batch_id)
    token = uuid.uuid4()
    attempt = (await db.execute(
        update(UploadBatch)
        .where(UploadBatch.id == bid, or_(UploadBatch.status == BatchStatus.QUEUED, leases.lapsed(UploadBatch)))
        .values(status=BatchStatus.PROCESSING, lease_token=token, lease_expires_at=leases.new_expiry(),
                attempts=UploadBatch.attempts + 1)
        .returning(UploadBatch.attempts)
    )).scalar_one_or_none()
    await db.commit()
    if attempt is None:
        return {"status": "skipped"}  # missing, finished, or a live worker has it
    metrics.CLAIMS.labels("batch", str(attempt > 1).lower()).inc()
    log.info("batch_claimed", batch_id=batch_id, attempt=attempt, worker=leases.WORKER)

    def fenced(**values):
        return (update(UploadBatch).where(UploadBatch.id == bid, UploadBatch.lease_token == token)
                .values(**values).returning(UploadBatch.id))

    try:
        return await _process_claimed(db, bid, batch_id, token, attempt, fenced)
    except Exception:
        await db.rollback()
        await db.execute(fenced(status=BatchStatus.FAILED, completed_at=func.now(), lease_token=None,
                                lease_expires_at=None))
        await db.commit()
        log.exception("batch_failed", batch_id=batch_id, attempt=attempt)
        return {"status": "error"}


async def _process_claimed(db: AsyncSession, bid: uuid.UUID, batch_id: str, token: uuid.UUID, attempt: int,
                           fenced) -> dict:
    from sqlalchemy import func

    from app.services import leases
    from app.services.extraction.pipeline import process_uploaded_file

    batch = await db.get(UploadBatch, bid, populate_existing=True)
    if batch is None:
        return {"status": "skipped"}  # purged after it was claimed

    stmt = (
        select(UploadedFile.id)
        .where(UploadedFile.batch_id == bid)
        .order_by(UploadedFile.created_at, UploadedFile.id)
    )
    file_ids = list((await db.execute(stmt)).scalars())

    processed = failed = pending = 0
    async with leases.kept(db, UploadBatch, bid, token) as lost:
        for fid in file_ids:
            await process_uploaded_file(db, fid)
            file = await db.get(UploadedFile, fid, populate_existing=True)
            # held by another live claim (a reprocess request, or a dead worker whose lease has not run out):
            # wait until it finishes or lapses, then take it over
            while file is not None and file.status is FileStatus.PROCESSING and not lost.is_set():
                await asyncio.sleep(settings.job_lease_seconds / 4)
                await process_uploaded_file(db, fid)
                file = await db.get(UploadedFile, fid, populate_existing=True)
            status = file.status if file is not None else FileStatus.FAILED
            if status is FileStatus.PENDING_OCR:
                pending += 1
            elif status is FileStatus.DONE:
                processed += 1
            else:
                failed += 1
            held = (await db.execute(fenced(processed_files=processed, failed_files=failed))).scalar_one_or_none()
            await db.commit()  # live progress for the polling endpoint
            if held is None or lost.is_set():
                log.warning("batch_lease_lost", batch_id=batch_id, worker=leases.WORKER)
                return {"status": "lease_lost"}

    final = BatchStatus.FAILED if failed == len(file_ids) and file_ids else BatchStatus.COMPLETED
    # ponytail: no cap on batch re-claims; files cap their own retries, so only a crash while finalising
    # could loop, and that has not been seen
    held = (await db.execute(fenced(status=final, completed_at=func.now(), lease_token=None,
                                    lease_expires_at=None))).scalar_one_or_none()
    if held is None:
        await db.rollback()
        log.warning("batch_lease_lost", batch_id=batch_id, worker=leases.WORKER)
        return {"status": "lease_lost"}
    if batch.kind is BatchKind.EMPLOYEE_REPO and failed < len(file_ids):
        await _populate_employee_repository(db, batch)
    elif batch.kind is BatchKind.COMPANY_LEAVE and failed < len(file_ids):
        from app.services.leave_service import import_leave_batch

        await import_leave_batch(db, batch)
    await db.commit()
    log.info("batch_done", batch_id=batch_id, processed=processed, failed=failed, pending=pending,
             attempt=attempt)
    return {"processed": processed, "failed": failed, "pending": pending}


async def _populate_employee_repository(db: AsyncSession, batch: UploadBatch) -> None:
    from sqlalchemy import select as sa_select

    from app.models.uploads import ExtractedRow
    from app.services.employee_service import upsert_from_extracted_rows, validate_employee_code

    stmt = (
        sa_select(ExtractedRow)
        .join(ExtractedRow.file)
        .where(UploadedFile.batch_id == batch.id)
        .order_by(ExtractedRow.file_id, ExtractedRow.row_index)
    )
    rows = (await db.execute(stmt)).scalars().unique().all()

    best_by_code: dict[str, dict] = {}
    review_by_code: dict[str, dict] = {}
    for row in rows:
        values = dict(row.data or {})
        code = str(values.get("employee_code") or "").strip()
        if not code or not validate_employee_code(code):
            continue
        if row.needs_review and not str(values.get("full_name") or "").strip():
            continue  # unreadable OCR rows must not poison the repository
        # Later files win field by field (re-upload semantics); fields they
        # leave blank keep the earlier values.
        best_by_code.setdefault(code, values).update(
            {k: v for k, v in values.items() if v}
        )
        review_by_code[code.lower()] = {
            "needs_review": row.needs_review,
            "note": row.review_note,
            "confidence": row.confidence,
        }

    created, updated = await upsert_from_extracted_rows(
        db,
        manager_id=batch.manager_id,
        rows_by_code=best_by_code,
        actor_id=batch.manager_id,
        review_by_code=review_by_code,
    )
    log.info("repository_populated", batch_id=str(batch.id),
             created=created, updated=updated)


# Settings shims kept local so tests can monkeypatch them.


def settings_max_files() -> int:
    from app.core.config import settings

    return settings.max_files_per_batch


def _max_file_bytes() -> int:
    from app.core.config import settings

    return settings.max_file_size_bytes


def _max_file_mb() -> int:
    from app.core.config import settings

    return settings.max_file_size_mb


async def purge_obsolete_batches(
    db: AsyncSession, *, actor: User, retention_days: int
) -> dict:
    """Hard-purges timesheet/repo batches past the retention window; employees are never touched.

    Blob deletion is best-effort: a storage failure must not roll back the DB purge.
    """
    from datetime import timedelta

    from sqlalchemy import select as sa_select

    from app.models.analysis import AnalysisRun, GeneratedReport
    from app.services.storage import get_storage

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)

    ids = list((await db.execute(sa_select(UploadBatch.id).where(UploadBatch.created_at < cutoff))).scalars())
    in_old = ids or [uuid.uuid4()]
    file_keys = list((await db.execute(
        sa_select(UploadedFile.storage_key).where(UploadedFile.batch_id.in_(in_old))
    )).scalars())
    report_keys = list((await db.execute(
        sa_select(GeneratedReport.storage_key)
        .join(AnalysisRun, AnalysisRun.id == GeneratedReport.run_id)
        .where(AnalysisRun.batch_id.in_(in_old))
    )).scalars())

    from sqlalchemy import delete as sa_delete

    # rows first: if storage then fails, a file is orphaned and logged, never a row left pointing at nothing
    await db.execute(sa_delete(UploadBatch).where(UploadBatch.id.in_(in_old)))
    await db.commit()

    storage = get_storage()
    for key in file_keys + report_keys:
        try:
            await asyncio.to_thread(storage.delete, key)
        except Exception as exc:  # noqa: BLE001 — blob cleanup is best-effort
            log.warning("purge_blob_failed", key=key, error=str(exc))

    await audit_service.record(
        db,
        action="PURGE_OBSOLETE_DATA",
        result=audit_service.AuditResult.SUCCESS,
        actor_user_id=actor.id,
        target_entity="upload_batch",
        target_id=None,
        metadata={"purged_batches": len(ids), "retention_days": retention_days},
    )
    return {"purged_batches": len(ids), "retention_days": retention_days, "cutoff": cutoff}
