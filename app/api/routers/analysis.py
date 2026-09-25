import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
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

router = APIRouter(tags=["analysis"])

RunViewer = Annotated[
    User,
    Depends(require_role(UserRole.MASTER_ADMIN, UserRole.EXECUTIVE, UserRole.MANAGER, UserRole.HR)),
]
ReportViewer = Annotated[
    User, Depends(require_role(UserRole.MASTER_ADMIN, UserRole.EXECUTIVE, UserRole.MANAGER))
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
    if actor.role is UserRole.MANAGER and run.manager_id != actor.id:
        raise HTTPException(403, detail={"code": "forbidden", "message": "Not your batch"})
    return run


@router.post("/batches/{batch_id}/analyze", status_code=202)
@user_limiter.limit(ANALYZE_LIMIT)
async def trigger_analyze(request: Request, batch_id: uuid.UUID, actor: AnalyzeTrigger, db: DB):
    batch = await db.get(UploadBatch, batch_id)
    if batch is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Batch not found"})
    if batch.manager_id != actor.id:
        raise HTTPException(
            403, detail={"code": "forbidden", "message": "You can only analyze your own batches"}
        )
    from app.services.analyze_service import AnalyzeRuleError, claim_analysis
    from app.services.jobs import dispatch_analysis

    try:
        run = await claim_analysis(db, batch, actor.id)
        result = await dispatch_analysis(str(batch_id), actor.id, str(run.id))
    except AnalyzeRuleError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            503, detail={"code": "queue_unavailable", "message": str(exc)[:200]}
        ) from exc
    if result is None:
        return JSONResponse(status_code=202, content={"status": "RUNNING", "batch_id": str(batch_id)})
    return result


@router.get("/batches/{batch_id}/analysis", response_model=RunDetailOut)
async def get_analysis(batch_id: uuid.UUID, actor: ReportViewer, db: DB):
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


@router.get("/batches/{batch_id}/export", operation_id="export_batch")
@router.post("/batches/{batch_id}/export", operation_id="export_batch_with_body")
async def export_batch(
    batch_id: uuid.UUID,
    actor: RunViewer,
    db: DB,
    request: Request,
    format: str = Query(default="xlsx", pattern="^(csv|xlsx|pdf|png)$"),
    columns: str | None = Query(default=None),
):
    """Pure reformatting of processed rows. GET serves the frontend download helper; POST is kept for API clients."""
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
    raw_rows = (await db.execute(stmt)).scalars().all()
    rows = [dict(r) for r in raw_rows]

    if cols:
        columns_out = cols
    elif batch.kind.value == "GETS":
        # Timesheets: identity + project columns, then ALL 31 day columns (a
        # missing column is indistinguishable from zero hours), then total.
        extras_keys: set[str] = set()
        for r in rows:
            extras_keys.update((r.get("extra") or {}).keys())
        fixed = ["employee_code", "full_name", "supplier", "job_family", "hour_type",
                 "project_id", "project_name", "task_id", "remarks"]
        day_cols = [f"day_{d:02d}" for d in range(1, 32)]
        tail = [c for c in ("total", "period") if c in extras_keys]
        tail += sorted(c for c in extras_keys if c.endswith(" leave"))
        columns_out = fixed + day_cols + tail
    else:
        columns_out = [
            "employee_code", "full_name", "official_email",
            "personal_email", "department",
        ]
    content_type, filename, exporter = EXPORTERS[fmt]
    data = await asyncio.to_thread(exporter, rows, columns_out)

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
async def download_report(request: Request, run_id: uuid.UUID, kind: str, actor: ReportViewer, db: DB):
    if kind not in ("summary.pdf", "3tab.xlsx"):
        raise HTTPException(404, detail={"code": "not_found", "message": "Unknown report kind"})
    report_kind = ReportKind.SUMMARY_PDF if kind.endswith("pdf") else ReportKind.EXCEL_3TAB

    stmt = (
        select(GeneratedReport)
        .join(AnalysisRun, AnalysisRun.id == GeneratedReport.run_id)
        .where(GeneratedReport.run_id == run_id, GeneratedReport.kind == report_kind)
        .order_by(GeneratedReport.created_at.desc())
        .limit(1)
    )
    report = (await db.execute(stmt)).scalar_one_or_none()
    if report is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Report not generated"})

    run = await db.get(AnalysisRun, run_id)
    if actor.role is UserRole.MANAGER and run.manager_id != actor.id:
        raise HTTPException(403, detail={"code": "forbidden", "message": "Not your report"})

    try:
        data = await asyncio.to_thread(get_storage().get_bytes, report.storage_key)
    except StorageError as exc:
        raise HTTPException(
            410, detail={"code": "gone", "message": "Report object missing from storage"}
        ) from exc

    media = "application/pdf" if report_kind is ReportKind.SUMMARY_PDF else (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return Response(content=data, media_type=media)


@router.post("/runs/{run_id}/resend")
async def resend_reports(run_id: uuid.UUID, actor: ReportViewer, db: DB):
    """Re-delivers the summary PDF + Excel to the uploading manager (dry-run aware)."""
    run = await db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Run not found"})
    if actor.role is UserRole.MANAGER and run.manager_id != actor.id:
        raise HTTPException(403, detail={"code": "forbidden", "message": "Not your report"})

    from app.services.reporting import email_reports_to_manager, generate_and_store_reports

    existing = (await db.execute(
        select(GeneratedReport.kind, GeneratedReport.storage_key)
        .where(GeneratedReport.run_id == run.id)
        .order_by(GeneratedReport.created_at)
    )).all()
    keys = {kind.value.lower(): key for kind, key in existing}
    if {"excel_3tab", "summary_pdf"} <= keys.keys():
        await email_reports_to_manager(await db.get(User, run.manager_id), keys)
    else:
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
