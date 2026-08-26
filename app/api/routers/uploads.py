"""Upload + batch status routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, require_role
from app.models.uploads import BatchKind, UploadBatch
from app.models.user import User, UserRole
from app.schemas.business import BatchDetailOut, BatchOut, FileStatusOut
from app.services import batch_service
from app.worker_tasks import process_batch_task

router = APIRouter(prefix="/uploads", tags=["uploads"])

ManagerOnly = Annotated[User, Depends(require_role(UserRole.MANAGER))]
BatchViewer = Annotated[
    User,
    Depends(require_role(UserRole.MASTER_ADMIN, UserRole.EXECUTIVE, UserRole.MANAGER)),
]


@router.post("", response_model=BatchOut, status_code=201)
async def create_upload(
    request: Request,
    files: list[UploadFile],
    actor: ManagerOnly,
    db: DB,
    kind: str = Query(description="EMPLOYEE_REPO or GETS"),
):
    """Multi-file upload (max 20 files). Content inspected via magic bytes;
    the batch is queued for sequential background processing."""
    _ = request
    try:
        batch_kind = BatchKind(kind.strip().upper())
    except ValueError as exc:
        raise HTTPException(
            422, detail={"code": "bad_kind", "message": "kind must be EMPLOYEE_REPO or GETS"}
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

    process_batch_task.delay(str(batch.id))
    # The eager/worker task commits through its own engine; re-read state so
    # the response reflects post-processing status instead of our snapshot.
    await db.refresh(batch)
    return BatchOut.model_validate(batch)


@router.get("/batches", response_model=list[BatchOut])
async def list_batches(actor: BatchViewer, db: DB):
    stmt = select(UploadBatch).order_by(desc(UploadBatch.created_at)).limit(100)
    if actor.role is UserRole.MANAGER:
        stmt = stmt.where(UploadBatch.manager_id == actor.id)
    rows = (await db.execute(stmt)).scalars().all()
    return [BatchOut.model_validate(b) for b in rows]


@router.get("/batches/{batch_id}", response_model=BatchDetailOut)
async def batch_status(batch_id: uuid.UUID, actor: BatchViewer, db: DB):
    """Live progress per file — poll this endpoint for UI status displays."""
    stmt = (
        select(UploadBatch)
        .where(UploadBatch.id == batch_id)
        .options(selectinload(UploadBatch.files))
    )
    batch = (await db.execute(stmt)).scalar_one_or_none()
    if batch is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Batch not found"})
    _assert_batch_visible(actor, batch)

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
            FileStatusOut.model_validate(f)
            for f in sorted(batch.files, key=lambda x: x.created_at)
        ],
    )


@router.post("/batches/{batch_id}/files/{file_id}/reprocess", response_model=FileStatusOut)
async def reprocess_file(
    batch_id: uuid.UUID,
    file_id: uuid.UUID,
    actor: BatchViewer,
    db: DB,
):
    """Retries a PENDING_OCR or FAILED file — e.g. after installing an OCR engine."""
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
    if file.status not in ("PENDING_OCR", "FAILED"):
        raise HTTPException(
            409,
            detail={"code": "not_retryable",
                    "message": f"File is {file.status.value}; only PENDING_OCR/FAILED retry"},
        )

    ok = await process_uploaded_file(db, file.id)
    await db.refresh(file)
    _ = ok
    return FileStatusOut.model_validate(file)


def _assert_batch_visible(actor: User, batch: UploadBatch) -> None:
    if actor.role is UserRole.HR:
        raise HTTPException(403, detail={"code": "forbidden", "message": "HR has no upload access"})
    if actor.role is UserRole.MANAGER and batch.manager_id != actor.id:
        raise HTTPException(403, detail={"code": "forbidden", "message": "Not your batch"})
