"""Per-file extraction orchestrator.

OCR runs on a dedicated thread pool (OCR_CONCURRENCY) so screenshots never starve the shared pool,
and no DB connection is held during OCR. Claiming a file is an atomic status transition.
"""

import asyncio
import os
import threading
import uuid as uuid_mod
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.uploads import ExtractedRow, FileStatus, UploadBatch, UploadedFile
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
            from app.core.config import settings

            _ocr_pool = ThreadPoolExecutor(
                max(1, settings.ocr_concurrency), thread_name_prefix="ocr", initializer=_lower_priority
            )
    return _ocr_pool


def _extract(content_type: str, data: bytes, kind: str | None = None):
    tables = readers.read_any(content_type, data)
    rows = [verify_row(r) for r in normalize_tables(tables, kind=kind)]
    meta: dict = {}
    for table in tables:
        sheet = (getattr(table, "meta", None) or {}).get("gets_sheet")
        if sheet:
            meta.setdefault("gets_sheets", []).append(sheet)
    return rows, meta


async def claim_file(db: AsyncSession, file_id: uuid_mod.UUID) -> bool:
    result = await db.execute(
        update(UploadedFile)
        .where(UploadedFile.id == file_id, UploadedFile.status.in_(CLAIMABLE))
        .values(status=FileStatus.PROCESSING, error_message=None)
        .returning(UploadedFile.id)
    )
    await db.commit()
    return result.scalar_one_or_none() is not None


async def process_uploaded_file(db: AsyncSession, file_id: uuid_mod.UUID) -> bool:
    if not await claim_file(db, file_id):
        return False  # already being processed (or done) elsewhere
    file = await db.get(UploadedFile, file_id, populate_existing=True)
    if file is None:
        return False

    try:
        from app.services.storage import get_storage

        batch = await db.get(UploadBatch, file.batch_id)
        kind = batch.kind.value if batch else None
        content_type = file.content_type_detected or ""
        await db.commit()  # release the connection before the slow part

        data = await asyncio.to_thread(get_storage().get_bytes, file.storage_key)
        rows, meta = await asyncio.get_running_loop().run_in_executor(
            _executor_for(content_type), _extract, content_type, data, kind
        )
        if not rows:
            raise NoRowsError(
                "No timesheet found in this file" if kind == "GETS" else "No data rows found in this file"
            )

        db.add_all(
            ExtractedRow(
                file_id=file.id,
                row_index=idx,
                data=row.values,
                confidence=row.confidence,
                needs_review=row.needs_review,
                review_note=row.review_note,
            )
            for idx, row in enumerate(rows)
        )
        file.rows_extracted = len(rows)
        file.extraction_meta = meta or None
        file.status = FileStatus.DONE
        file.processed_at = datetime.now(UTC)
        await db.commit()
        log.info("file_processed", file_id=str(file.id), rows=file.rows_extracted)
        return True

    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        file = await db.get(UploadedFile, file_id, populate_existing=True)
        if isinstance(exc, OcrUnavailableError):
            # Engine missing, not a bad file: keep it retryable.
            file.status = FileStatus.PENDING_OCR
            file.error_message = str(exc)[:300]
        else:
            file.status = FileStatus.FAILED
            file.error_message = (
                str(exc) if isinstance(exc, NoRowsError) else f"{type(exc).__name__}: {str(exc)[:300]}"
            )
        file.processed_at = datetime.now(UTC)
        await db.commit()
        log.warning(
            "file_not_processed", file_id=str(file.id),
            status=file.status.value, error=file.error_message,
        )
        return False
