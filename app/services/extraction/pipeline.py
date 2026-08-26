"""Per-file processing orchestrator used by the Celery task."""

import hashlib
import uuid as uuid_mod
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.uploads import ExtractedRow, FileStatus, UploadedFile
from app.services.extraction import readers
from app.services.extraction.llm_verify import verify_row
from app.services.extraction.normalize import normalize_tables
from app.services.extraction.ocr import OcrUnavailableError

log = get_logger("extraction")


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def process_uploaded_file(db: AsyncSession, file_id: uuid_mod.UUID) -> bool:
    """Runs the full extraction for one uploaded file. Returns success."""
    file = await db.get(UploadedFile, file_id)
    if file is None:
        return False

    file.status = FileStatus.PROCESSING
    await db.commit()

    try:
        from app.services.storage import get_storage

        data = get_storage().get_bytes(file.storage_key)

        tables = readers.read_any(file.content_type_detected or "", data)
        rows = normalize_tables(tables)

        # LLM verification pass over flagged rows.
        verified_rows = [verify_row(r) for r in rows]

        for idx, row in enumerate(verified_rows):
            db.add(
                ExtractedRow(
                    file_id=file.id,
                    row_index=idx,
                    data=row.values,
                    confidence=row.confidence,
                    needs_review=row.needs_review,
                    review_note=row.review_note,
                )
            )
        file.rows_extracted = len(verified_rows)
        file.status = FileStatus.DONE
        file.processed_at = datetime.now(UTC)
        await db.commit()
        log.info("file_processed", file_id=str(file.id), rows=file.rows_extracted)
        return True

    except Exception as exc:  # noqa: BLE001 — mark failure with reason
        if "OcrUnavailableError" in type(exc).__name__ or isinstance(
            exc, OcrUnavailableError
        ):
            # Engine missing, not a bad file: keep it retryable.
            file.status = FileStatus.PENDING_OCR
            file.error_message = str(exc)[:300]
        else:
            file.status = FileStatus.FAILED
            file.error_message = f"{type(exc).__name__}: {str(exc)[:300]}"
        file.processed_at = datetime.now(UTC)
        await db.commit()
        log.warning(
            "file_not_processed", file_id=str(file.id),
            status=file.status.value, error=file.error_message,
        )
        return False
