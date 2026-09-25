import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, require_role
from app.core.rate_limit import UPLOAD_LIMIT, user_limiter
from app.models.uploads import BatchKind, ExtractedRow, FileStatus, UploadBatch, UploadedFile
from app.models.user import User, UserRole
from app.schemas.business import BatchDetailOut, BatchOut, FileStatusOut
from app.services import batch_service
from app.services.jobs import dispatch_batch

router = APIRouter(prefix="/uploads", tags=["uploads"])

ManagerOnly = Annotated[User, Depends(require_role(UserRole.MANAGER))]
# Read access to batches. HR is scoped to their own manager's batches by
# `_assert_batch_visible`/`list_batches` — download-only, never mutating.
BatchViewer = Annotated[
    User,
    Depends(require_role(UserRole.MASTER_ADMIN, UserRole.EXECUTIVE, UserRole.MANAGER, UserRole.HR)),
]
FileReprocessor = Annotated[
    User,
    Depends(require_role(UserRole.MASTER_ADMIN, UserRole.EXECUTIVE, UserRole.MANAGER)),
]


@router.post("", response_model=BatchOut, status_code=201)
@user_limiter.limit(UPLOAD_LIMIT)
async def create_upload(
    request: Request,
    files: list[UploadFile],
    actor: ManagerOnly,
    db: DB,
    kind: str = Query(description="EMPLOYEE_REPO, GETS or COMPANY_LEAVE"),
):
    """Multi-file upload (max 20). Content is sniffed by magic bytes and the batch is queued;
    poll GET /uploads/batches/{id} for per-file progress."""
    try:
        batch_kind = BatchKind(kind.strip().upper())
    except ValueError as exc:
        raise HTTPException(
            422,
            detail={"code": "bad_kind",
                    "message": "kind must be EMPLOYEE_REPO, GETS or COMPANY_LEAVE"},
        ) from exc

    contents: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        contents.append((f.filename or "unnamed", data))

    try:
        batch = await batch_service.create_batch(
            db, manager=actor, kind=batch_kind, files=contents
        )
    except batch_service.UploadRuleError as exc:
        raise HTTPException(
            exc.status_code, detail={"code": exc.code, "message": exc.message}
        ) from exc

    await db.commit()
    await dispatch_batch(str(batch.id))
    # inline mode has already processed the batch through its own session
    await db.refresh(batch)
    return BatchOut.model_validate(batch)


@router.get("/batches", response_model=list[BatchOut])
async def list_batches(
    actor: BatchViewer,
    db: DB,
    kind: BatchKind | None = Query(default=None, description="EMPLOYEE_REPO or GETS"),
):
    stmt = select(UploadBatch).order_by(desc(UploadBatch.created_at)).limit(100)
    if kind is not None:
        stmt = stmt.where(UploadBatch.kind == kind)
    if actor.role is UserRole.MANAGER:
        stmt = stmt.where(UploadBatch.manager_id == actor.id)
    elif actor.role is UserRole.HR:
        if actor.manager_id is None:
            return []
        stmt = stmt.where(UploadBatch.manager_id == actor.manager_id)
    rows = (await db.execute(stmt)).scalars().all()
    manager_ids = {b.manager_id for b in rows}
    users = {
        u.id: u
        for u in (
            await db.execute(select(User).where(User.id.in_(manager_ids)))
        ).scalars()
    } if manager_ids else {}
    out = []
    for b in rows:
        o = BatchOut.model_validate(b)
        u = users.get(b.manager_id)
        if u is not None:
            o.manager_email = u.email
            o.manager_name = u.full_name
        out.append(o)
    return out


@router.get("/batches/{batch_id}", response_model=BatchDetailOut)
async def batch_status(batch_id: uuid.UUID, actor: BatchViewer, db: DB):
    stmt = (
        select(UploadBatch)
        .where(UploadBatch.id == batch_id)
        .options(selectinload(UploadBatch.files))
    )
    batch = (await db.execute(stmt)).scalar_one_or_none()
    if batch is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Batch not found"})
    _assert_batch_visible(actor, batch)

    from sqlalchemy import func as sa_func

    review_counts: dict[uuid.UUID, int] = {}
    if batch.files:
        counts_stmt = (
            select(
                ExtractedRow.file_id,
                sa_func.count().filter(ExtractedRow.needs_review.is_(True)).label("flagged"),
            )
            .where(ExtractedRow.file_id.in_([f.id for f in batch.files]))
            .group_by(ExtractedRow.file_id)
        )
        for fid, flagged in (await db.execute(counts_stmt)).all():
            review_counts[fid] = int(flagged or 0)

    def _file_out(f):
        out = file_out(f)
        out.needs_review_count = review_counts.get(f.id, 0)
        return out

    return BatchDetailOut(
        id=batch.id,
        kind=batch.kind.value,
        status=batch.status.value,
        total_files=batch.total_files,
        processed_files=batch.processed_files,
        failed_files=batch.failed_files,
        created_at=batch.created_at,
        completed_at=batch.completed_at,
        files=[
            _file_out(f) for f in sorted(batch.files, key=lambda x: x.created_at)
        ],
    )


@router.get("/batches/{batch_id}/review-rows")
async def review_rows(batch_id: uuid.UUID, actor: BatchViewer, db: DB):
    """Flagged extracted rows across a batch (the 'Needs Review' tab), with the reason for each row."""
    stmt = (
        select(UploadBatch)
        .where(UploadBatch.id == batch_id)
        .options(selectinload(UploadBatch.files))
    )
    batch = (await db.execute(stmt)).scalar_one_or_none()
    if batch is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Batch not found"})
    _assert_batch_visible(actor, batch)

    stmt = (
        select(ExtractedRow, UploadedFile.original_filename)
        .join(UploadedFile, UploadedFile.id == ExtractedRow.file_id)
        .where(
            ExtractedRow.file_id.in_([f.id for f in batch.files]),
            ExtractedRow.needs_review.is_(True),
        )
        .order_by(UploadedFile.original_filename, ExtractedRow.row_index)
    )
    rows = (await db.execute(stmt)).all()
    return {
        "items": [
            {
                "id": r.id,
                "file_id": str(r.file_id),
                "file_name": fn,
                "row_index": r.row_index,
                "review_note": r.review_note,
                "confidence": float(r.confidence) if r.confidence is not None else None,
                "data": r.data,
            }
            for r, fn in rows
        ]
    }


@router.post("/batches/{batch_id}/files/{file_id}/reprocess", response_model=FileStatusOut)
@user_limiter.limit(UPLOAD_LIMIT)
async def reprocess_file(
    request: Request,
    batch_id: uuid.UUID,
    file_id: uuid.UUID,
    actor: FileReprocessor,
    db: DB,
    force: bool = Query(
        default=False,
        description="Re-extract an already-DONE file (e.g. after extraction logic improves)",
    ),
):
    """Retries a PENDING_OCR/FAILED file; with force=true also re-extracts a
    DONE file without a fresh upload."""
    from sqlalchemy import delete

    from app.services.extraction.pipeline import process_uploaded_file

    stmt = (
        select(UploadBatch)
        .where(UploadBatch.id == batch_id)
        .options(selectinload(UploadBatch.files))
    )
    batch = (await db.execute(stmt)).scalar_one_or_none()
    if batch is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Batch not found"})
    _assert_batch_visible(actor, batch)

    file = next((f for f in batch.files if f.id == file_id), None)
    if file is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "File not found"})

    if file.status is FileStatus.PROCESSING:
        raise HTTPException(
            409, detail={"code": "busy", "message": "File is being processed right now"}
        )
    retryable = file.status in (FileStatus.PENDING_OCR, FileStatus.FAILED)
    if not retryable and not force:
        raise HTTPException(
            409,
            detail={
                "code": "not_retryable",
                "message": "File is DONE; pass force=true to re-extract it",
            },
        )

    if not retryable:
        # Clear the prior extraction so improved logic re-inserts fresh rows;
        # the status guard makes a concurrent force-reprocess a no-op.
        from sqlalchemy import update

        reset = await db.execute(
            update(UploadedFile)
            .where(UploadedFile.id == file.id, UploadedFile.status == FileStatus.DONE)
            .values(status=FileStatus.QUEUED)
            .returning(UploadedFile.id)
        )
        if reset.scalar_one_or_none() is None:
            await db.rollback()
            raise HTTPException(
                409, detail={"code": "busy", "message": "File is being processed right now"}
            )
        await db.execute(delete(ExtractedRow).where(ExtractedRow.file_id == file.id))
        await db.commit()

    await process_uploaded_file(db, file.id)
    await db.refresh(file)
    return file_out(file)


def file_out(f: UploadedFile) -> FileStatusOut:
    out = FileStatusOut.model_validate(f)
    sheets = (f.extraction_meta or {}).get("gets_sheets") or []
    if sheets:
        statuses = [s.get("status") for s in sheets]
        out.sheet_status = (
            "NEEDS_REVIEW" if "NEEDS_REVIEW" in statuses
            else "CORRECTED" if "CORRECTED" in statuses else "VERIFIED"
        )
        out.sheet_period = sheets[0].get("period")
        out.sheet_employee = sheets[0].get("employee_name")
    return out


async def _load_file(db, actor: User, batch_id: uuid.UUID, file_id: uuid.UUID):
    stmt = (
        select(UploadBatch)
        .where(UploadBatch.id == batch_id)
        .options(selectinload(UploadBatch.files))
    )
    batch = (await db.execute(stmt)).scalar_one_or_none()
    if batch is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Batch not found"})
    _assert_batch_visible(actor, batch)
    file = next((f for f in batch.files if f.id == file_id), None)
    if file is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "File not found"})
    return batch, file


@router.get("/batches/{batch_id}/files/{file_id}/extraction")
async def file_extraction(batch_id: uuid.UUID, file_id: uuid.UUID, actor: BatchViewer, db: DB):
    """Rows plus the document report (for GETS screenshots: cell grid, statuses, totals checks)."""
    _batch, file = await _load_file(db, actor, batch_id, file_id)
    rows = (
        await db.execute(
            select(ExtractedRow)
            .where(ExtractedRow.file_id == file.id)
            .order_by(ExtractedRow.row_index)
        )
    ).scalars().all()
    return {
        "file": file_out(file).model_dump(mode="json"),
        "meta": file.extraction_meta or {},
        "rows": [
            {
                "id": r.id, "row_index": r.row_index, "data": r.data,
                "confidence": r.confidence, "needs_review": r.needs_review,
                "review_note": r.review_note,
            }
            for r in rows
        ],
    }


@router.get("/batches/{batch_id}/files/{file_id}/content")
async def file_content(batch_id: uuid.UUID, file_id: uuid.UUID, actor: BatchViewer, db: DB):
    import asyncio

    from fastapi.responses import Response

    from app.services.storage import StorageError, get_storage

    _batch, file = await _load_file(db, actor, batch_id, file_id)
    try:
        data = await asyncio.to_thread(get_storage().get_bytes, file.storage_key)
    except StorageError as exc:
        raise HTTPException(410, detail={"code": "gone", "message": "File missing from storage"}) from exc
    return Response(
        content=data,
        media_type=file.content_type_detected or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=3600",
                 "Content-Disposition": f'inline; filename="{file.original_filename}"'},
    )


def _assert_batch_visible(actor: User, batch: UploadBatch) -> None:
    if actor.role is UserRole.HR:
        if actor.manager_id is None or batch.manager_id != actor.manager_id:
            raise HTTPException(403, detail={"code": "forbidden", "message": "Not your manager's batch"})
        return
    if actor.role is UserRole.MANAGER and batch.manager_id != actor.id:
        raise HTTPException(403, detail={"code": "forbidden", "message": "Not your batch"})
