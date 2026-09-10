"""Analysis + export + report routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import DB, require_role
from app.core.rate_limit import ANALYZE_LIMIT, EXPORT_LIMIT, user_limiter
from app.models.analysis import AnalysisRun, GeneratedReport, ReportKind, ViolationResult
from app.models.uploads import UploadBatch
from app.models.user import User, UserRole
from app.schemas.business import ExportRequest, RunDetailOut, RunTotals, ViolationOut
from app.services import audit_service
from app.services.exporters import EXPORTERS
from app.services.storage import StorageError, get_storage
from app.worker_tasks import run_analyze_task

router = APIRouter(tags=["analysis"])

RunViewer = Annotated[
    User,
    Depends(require_role(UserRole.MASTER_ADMIN, UserRole.EXECUTIVE, UserRole.MANAGER, UserRole.HR)),
]
AnalyzeTrigger = Annotated[User, Depends(require_role(UserRole.MANAGER))]


async def _get_run_scoped(db, actor: User, batch_id: uuid.UUID) -> AnalysisRun:
    stmt = select(AnalysisRun).where(AnalysisRun.batch_id == batch_id)
    run = (await db.execute(stmt)).scalar_one_or_none()
    if run is None:
        raise HTTPException(
            404,
            detail={"code": "not_found", "message": "No analysis for this batch"},
        )
    if actor.role is UserRole.HR:
        raise HTTPException(
            403,
            detail={"code": "forbidden", "message": "HR has no analysis access"},
        )
    if actor.role is UserRole.MANAGER and run.manager_id != actor.id:
        raise HTTPException(403, detail={"code": "forbidden", "message": "Not your batch"})
    return run


@router.post("/batches/{batch_id}/analyze", status_code=202)
@user_limiter.limit(ANALYZE_LIMIT)
async def trigger_analyze(request: Request, batch_id: uuid.UUID, actor: AnalyzeTrigger, db: DB):
    """Runs violation analysis on a completed GETS batch (Manager, own batch)."""
    batch = await db.get(UploadBatch, batch_id)
    if batch is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Batch not found"})
    if batch.manager_id != actor.id:
        raise HTTPException(
            403, detail={"code": "forbidden", "message": "You can only analyze your own batches"}
        )
    try:
        # With a live broker this returns immediately (202 semantics); under
        # celery_task_always_eager it runs inline so callers get the result.
        async_result = run_analyze_task.delay(str(batch_id))
    except Exception as exc:  # noqa: BLE001 — broker unavailable
        raise HTTPException(
            503, detail={"code": "queue_unavailable", "message": str(exc)[:200]}
        ) from exc

    if getattr(async_result, "eager", False) or hasattr(async_result, "get"):
        try:
            return async_result.get(timeout=300)
        except Exception as exc:  # noqa: BLE001 — surface task failures
            raise HTTPException(
                500, detail={"code": "analysis_failed", "message": str(exc)[:200]}
            ) from exc


@router.get("/batches/{batch_id}/analysis", response_model=RunDetailOut)
async def get_analysis(batch_id: uuid.UUID, actor: RunViewer, db: DB):
    run = await _get_run_scoped(db, actor, batch_id)
    violations = (
        await db.execute(
            select(ViolationResult)
            .where(ViolationResult.run_id == run.id)
            .order_by(ViolationResult.employee_code)
        )
    ).scalars().all()

    return RunDetailOut(
        run_id=str(run.id),
        batch_id=str(run.batch_id),
        manager_id=str(run.manager_id),
        status=run.status.value,
        started_at=run.started_at,
        completed_at=run.completed_at,
        totals=RunTotals(
            files_processed=run.files_processed,
            rows_processed=run.rows_processed,
            matched=run.matched,
            violations=run.violations,
            emails_sent=run.emails_sent,
            emails_missing=int(run.emails_missing),
            emails_errored=run.emails_errored,
            skipped=run.skipped,
        ),
        violations=[ViolationOut.model_validate(v) for v in violations],
        skipped_rows=run.skipped_rows or [],
    )


@router.api_route("/batches/{batch_id}/export", methods=["GET", "POST"])
async def export_batch(
    batch_id: uuid.UUID,
    actor: RunViewer,
    db: DB,
    request: Request,
    format: str = Query(default="xlsx", pattern="^(csv|xlsx|pdf|png)$"),
    columns: str | None = Query(default=None),
):
    """Pure reformatting of processed rows — no violation logic involved.

    GET (query params) is what the frontend download helper uses; POST with a
    JSON ExportRequest body is kept for API clients."""
    batch = await db.get(UploadBatch, batch_id)
    if batch is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Batch not found"})
    if actor.role is UserRole.HR:
        if actor.manager_id is None or batch.manager_id != actor.manager_id:
            raise HTTPException(403, detail={"code": "forbidden", "message": "Not your manager's batch"})
    elif actor.role is UserRole.MANAGER and batch.manager_id != actor.id:
        raise HTTPException(403, detail={"code": "forbidden", "message": "Not your batch"})

    if request.method == "POST":
        body = ExportRequest.model_validate(await request.json())
        fmt, cols = body.format, body.columns
    else:
        fmt, cols = format, columns.split(",") if columns else None

    from app.models.uploads import ExtractedRow

    stmt = (
        select(ExtractedRow.data)
        .join(ExtractedRow.file)
        .where(UploadedFile_in_batch(batch_id))
        .order_by(ExtractedRow.file_id, ExtractedRow.row_index)
        .limit(10000)
    )
    # select(ExtractedRow.data) yields one column; scalars() unwraps each row dict.
    raw_rows = (await db.execute(stmt)).scalars().all()
    rows = [dict(r) for r in raw_rows]

    if cols:
        columns_out = cols
    elif batch.kind.value == "GETS":
        # Timesheets: fixed left columns, then day columns (sorted by day
        # number), then total. Anything else observed trails on.
        extras_keys: set[str] = set()
        for r in rows:
            extras_keys.update((r.get("extra") or {}).keys())
        # A timesheet grid is positional: always emit all 31 day columns even
        # when empty — a missing column is indistinguishable from zero hours.
        day_cols = [f"day_{d:02d}" for d in range(1, 32)]
        tail = sorted(extras_keys - set(day_cols) - {"hour_type", "project_id",
                     "project_name", "task_id", "remarks", "total"})
        columns_out = [
            "employee_code", "full_name", "hour_type", "project_id",
            "project_name", "task_id", "remarks",
        ] + day_cols + (["total"] if "total" in extras_keys else []) + tail
    else:
        columns_out = [
            "employee_code", "full_name", "official_email",
            "personal_email", "department",
        ]
    content_type, filename, exporter = EXPORTERS[fmt]
    data = exporter(rows, columns_out)

    await audit_service.record(
        db,
        action="EXPORT_BATCH",
        result=audit_service.AuditResult.SUCCESS,
        actor_user_id=actor.id,
        target_entity="batch",
        target_id=str(batch_id),
        metadata={"format": fmt, "rows": len(rows)},
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def UploadedFile_in_batch(batch_id: uuid.UUID):
    from app.models.uploads import UploadedFile

    return UploadedFile.batch_id == batch_id


@router.get("/runs/{run_id}/reports/{kind}")
@user_limiter.limit(EXPORT_LIMIT)
async def download_report(request: Request, run_id: uuid.UUID, kind: str, actor: RunViewer, db: DB):
    """Summary PDF / 3-tab Excel downloads — Manager own, MA/EXEC all."""
    if kind not in ("summary.pdf", "3tab.xlsx"):
        raise HTTPException(404, detail={"code": "not_found", "message": "Unknown report kind"})
    report_kind = ReportKind.SUMMARY_PDF if kind.endswith("pdf") else ReportKind.EXCEL_3TAB

    stmt = (
        select(GeneratedReport)
        .join(AnalysisRun, AnalysisRun.id == GeneratedReport.run_id)
        .where(GeneratedReport.run_id == run_id, GeneratedReport.kind == report_kind)
    )
    report = (await db.execute(stmt)).scalar_one_or_none()
    if report is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Report not generated"})

    run = await db.get(AnalysisRun, run_id)
    if actor.role is UserRole.HR:
        raise HTTPException(403, detail={"code": "forbidden", "message": "HR has no report access"})
    if actor.role is UserRole.MANAGER and run.manager_id != actor.id:
        raise HTTPException(403, detail={"code": "forbidden", "message": "Not your report"})

    try:
        data = get_storage().get_bytes(report.storage_key)
    except StorageError as exc:
        raise HTTPException(
            410, detail={"code": "gone", "message": "Report object missing from storage"}
        ) from exc

    media = "application/pdf" if report_kind is ReportKind.SUMMARY_PDF else (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return Response(content=data, media_type=media)


@router.post("/runs/{run_id}/resend")
async def resend_reports(run_id: uuid.UUID, actor: RunViewer, db: DB):
    """Re-delivers summary PDF + 3-tab Excel to the uploading manager.

    MA/EXEC may trigger for visibility mirroring; dry-run mode records intent."""
    run = await db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Run not found"})
    if actor.role is UserRole.HR:
        raise HTTPException(403, detail={"code": "forbidden", "message": "HR has no report access"})
    if actor.role is UserRole.MANAGER and run.manager_id != actor.id:
        raise HTTPException(403, detail={"code": "forbidden", "message": "Not your report"})

    from app.services.reporting import generate_and_store_reports

    keys = await generate_and_store_reports(db, run)
    await audit_service.record(
        db,
        action="RESEND_REPORTS",
        result=audit_service.AuditResult.SUCCESS,
        actor_user_id=actor.id,
        target_entity="analysis_run",
        target_id=str(run.id),
        metadata={"attachments": sorted(keys.values())},
    )
    return {"resent": True, "attachments": sorted(keys.values())}
