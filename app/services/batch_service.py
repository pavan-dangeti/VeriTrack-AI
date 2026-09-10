"""Upload batch lifecycle: create (validated), process sequentially, poll."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.uploads import (
    BatchKind,
    BatchStatus,
    FileStatus,
    UploadBatch,
    UploadedFile,
)
from app.models.user import User, UserRole
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


def assert_can_upload(actor: User, kind: BatchKind) -> None:
    """Permission matrix: uploads are Manager-only; MA/EXEC have view-only."""
    if actor.role is not UserRole.MANAGER:
        raise UploadRuleError(
            403,
            "upload_forbidden",
            "Only Managers upload Employee/GETS data (your role has view-only access)",
        )


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

    storage = get_storage()
    batch = UploadBatch(manager_id=manager.id, kind=kind, total_files=len(files))
    db.add(batch)
    await db.flush()

    for filename, content in files:
        ext_ok = any(filename.lower().endswith(e) for e in ALLOWED_EXTENSIONS)
        if not ext_ok:
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
            from app.services.file_validation import sniff_content_type

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

        key = build_key(
            manager_id=str(manager.id), kind=kind.value, batch_id=str(batch.id),
            filename=filename,
        )
        stored = storage.put(key, __import__("io").BytesIO(content), len(content))

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


async def get_batch_scoped(db: AsyncSession, actor: User, batch_id: uuid.UUID) -> UploadBatch:
    batch = await db.get(UploadBatch, batch_id)
    if batch is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Batch not found"})
    # Query-layer scoping: managers see only their own batches.
    if actor.role is UserRole.MANAGER and batch.manager_id != actor.id:
        raise HTTPException(403, detail={"code": "forbidden", "message": "Not your batch"})
    if actor.role is UserRole.HR:
        raise HTTPException(403, detail={"code": "forbidden", "message": "HR has no upload access"})
    return batch


async def run_batch_processing(db: AsyncSession, batch_id: str) -> dict:
    """Sequential per-batch processing (spec: one file at a time)."""
    batch = await db.get(UploadBatch, uuid.UUID(batch_id))
    if batch is None:
        return {"status": "missing"}

    batch.status = BatchStatus.PROCESSING
    await db.commit()

    stmt = (
        select(UploadedFile)
        .where(UploadedFile.batch_id == batch.id)
        .order_by(UploadedFile.created_at, UploadedFile.id)
    )
    files = (await db.execute(stmt)).scalars().all()

    processed = failed = pending = 0
    for file in files:
        from app.services.extraction.pipeline import process_uploaded_file

        ok = await process_uploaded_file(db, file.id)
        await db.refresh(file)
        if file.status is FileStatus.PENDING_OCR:
            pending += 1
        elif ok:
            processed += 1
        else:
            failed += 1
        batch.processed_files = processed
        batch.failed_files = failed
        await db.commit()  # live progress for the polling endpoint

    batch.status = (
        BatchStatus.FAILED if failed == len(files) and files else BatchStatus.COMPLETED
    )
    batch.completed_at = datetime.now(UTC)

    # Employee-repo batches feed the repository in the same pass.
    if batch.kind is BatchKind.EMPLOYEE_REPO and failed < len(files):
        await _populate_employee_repository(db, batch)
        batch = await db.get(UploadBatch, batch.id)  # refresh state

    await db.commit()
    log.info("batch_done", batch_id=batch_id, processed=processed, failed=failed)
    return {"processed": processed, "failed": failed}


async def _populate_employee_repository(db: AsyncSession, batch: UploadBatch) -> None:
    """Upserts extracted EMPLOYEE_REPO rows into the manager's repository."""
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
        # Later files win (re-upload semantics); earlier duplicates are kept too.
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
        rows_by_code=best_by_code,  # original casing preserved
        actor_id=batch.manager_id,
        review_by_code=review_by_code,
    )
    log.info("repository_populated", batch_id=str(batch.id),
             created=created, updated=updated)


# --- settings shims kept local so tests can monkeypatch cleanly ---------------


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
    """Hard-purge GETS/repo batches (and their files/reports) older than the
    retention window. Employees are NEVER touched — their records are
    soft-delete/versioned and kept. Storage blobs best-effort: a blob failure
    must not roll back the DB purge."""
    from datetime import timedelta

    from sqlalchemy import select as sa_select

    from app.models.analysis import AnalysisRun, GeneratedReport
    from app.services.storage import get_storage

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)

    old = (
        await db.execute(
            sa_select(UploadBatch).where(UploadBatch.created_at < cutoff)
        )
    ).scalars()
    ids = [b.id for b in old]
    storage = get_storage()

    file_keys = []
    for b in old:
        for f in b.files:
            file_keys.append(f.storage_key)
    report_keys = list(
        (
            await db.execute(
                sa_select(GeneratedReport.storage_key)
                .join(AnalysisRun, AnalysisRun.id == GeneratedReport.run_id)
                .where(AnalysisRun.batch_id.in_(ids or [uuid.uuid4()]))
            )
        ).scalars()
    )

    for key in file_keys + report_keys:
        try:
            storage.delete(key)
        except Exception as exc:  # noqa: BLE001 — blob cleanup is best-effort
            log.warning("purge_blob_failed", key=key, error=str(exc))

    from sqlalchemy import delete as sa_delete

    await db.execute(sa_delete(UploadBatch).where(UploadBatch.id.in_(ids or [uuid.uuid4()])))
    await db.commit()

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
