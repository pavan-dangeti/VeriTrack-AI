"""Analysis orchestration: run the GETS rule over a processed batch,
persist violations (deduped), resolve emails, send via Graph, build reports."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.analysis import (
    AnalysisRun,
    AnalysisStatus,
    EmailStatus,
    ViolationResult,
)
from app.models.employees import Employee, EmployeeVersion
from app.models.uploads import (
    BatchKind,
    BatchStatus,
    ExtractedRow,
    UploadBatch,
    UploadedFile,
)
from app.services import audit_service, gets_rules

log = get_logger("analyze")


class AnalyzeRuleError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


async def _repository_lookup(db: AsyncSession, manager_id) -> dict[str, dict]:
    stmt = (
        select(Employee, EmployeeVersion)
        .join(EmployeeVersion, EmployeeVersion.id == Employee.current_version_id, isouter=True)
        .where(Employee.manager_id == manager_id, Employee.is_deleted.is_(False))
    )
    lookup: dict[str, dict] = {}
    for employee, version in (await db.execute(stmt)).all():
        if version is None:
            continue
        lookup[employee.employee_code.strip().lower()] = {
            "full_name": version.full_name,
            "official_email": version.official_email,
            "personal_email": version.personal_email,
            "department": version.department,
        }
    return lookup


async def execute_analysis(db: AsyncSession, batch_id: str, triggered_by=None) -> dict:
    batch = await db.get(UploadBatch, uuid.UUID(batch_id))
    if batch is None:
        raise AnalyzeRuleError(404, "not_found", "Batch not found")
    if batch.kind is not BatchKind.GETS:
        raise AnalyzeRuleError(400, "wrong_kind", "Analyze runs on GETS batches only")
    if batch.status not in (BatchStatus.COMPLETED, BatchStatus.FAILED):
        raise AnalyzeRuleError(409, "not_ready", "Batch processing has not completed yet")

    existing = (
        await db.execute(select(AnalysisRun).where(AnalysisRun.batch_id == batch.id))
    ).scalar_one_or_none()
    if existing is not None:
        raise AnalyzeRuleError(409, "already_analyzed", "This batch was already analyzed")

    run = AnalysisRun(
        batch_id=batch.id,
        manager_id=batch.manager_id,
        triggered_by=triggered_by,
        status=AnalysisStatus.RUNNING,
    )
    db.add(run)
    await db.commit()

    try:
        repo = await _repository_lookup(db, batch.manager_id)

        stmt = (
            select(ExtractedRow)
            .join(UploadedFile, UploadedFile.id == ExtractedRow.file_id)
            .where(UploadedFile.batch_id == batch.id)
            .order_by(ExtractedRow.file_id, ExtractedRow.row_index)
        )
        rows = (await db.execute(stmt)).scalars().unique().all()

        counts = {"rows_processed": 0, "matched": 0, "violations": 0, "skipped": 0}
        skip_log: list[dict] = []
        seen_codes: set[str] = set()  # first occurrence wins per run

        for row in rows:
            values = row.data or {}
            status, payload = gets_rules.check_row(row_values=values, repo_lookup=repo)

            if status in ("BAD_ID_FORMAT", "NOT_IN_REPO", "MISSING_COLUMNS"):
                counts["skipped"] += 1
                skip_log.append({"status": status, **payload})
                continue

            counts["rows_processed"] += 1
            code_lower = payload["employee_code"].lower()

            if status == "NO_VIOLATION":
                counts["matched"] += 1
                continue

            # MATCHED_VIOLATION — dedup: one result row per employee per run.
            # Repeat appearances in later files change nothing (one email).
            if code_lower in seen_codes:
                continue
            seen_codes.add(code_lower)
            counts["matched"] += 1
            counts["violations"] += 1
            db.add(
                ViolationResult(
                    run_id=run.id,
                    manager_id=batch.manager_id,
                    employee_code=payload["employee_code"],
                    employee_name=payload.get("employee_name"),
                    customer_leave_value=payload.get("customer_leave_value"),
                    sacha_leave_value=payload.get("sacha_leave_value"),
                    violation_reason=payload.get("violation_reason", ""),
                    email_to=payload.get("email_to"),
                    email_status=(
                        EmailStatus.PENDING
                        if payload.get("email_to")
                        else EmailStatus.SKIPPED_NO_EMAIL
                    ),
                )
            )

        await db.commit()

        # ---- dispatch phase -------------------------------------------------
        from app.services.emailer import dispatch_violation_emails

        sent, errored = await dispatch_violation_emails(db, run)

        run.files_processed = batch.total_files
        run.rows_processed = counts["rows_processed"]
        run.matched = counts["matched"]
        run.violations = counts["violations"]
        run.emails_sent = sent
        run.emails_errored = errored
        run.emails_missing = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(ViolationResult)
                    .where(
                        ViolationResult.run_id == run.id,
                        ViolationResult.email_status == EmailStatus.SKIPPED_NO_EMAIL,
                    )
                )
            ).scalar_one()
        )
        run.skipped = counts["skipped"]
        run.skipped_rows = skip_log[:500]
        run.status = AnalysisStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        await db.commit()

        # ---- reports ----------------------------------------------------------
        from app.services.reporting import generate_and_store_reports

        report_info = await generate_and_store_reports(db, run)

        log.info(
            "analyze_complete",
            run_id=str(run.id),
            violations=run.violations,
            emails_sent=sent,
            missing=run.emails_missing,
            skipped=counts["skipped"],
            reports=report_info,
        )
        await audit_service.record(
            db,
            action="RUN_ANALYZE",
            result=audit_service.AuditResult.SUCCESS,
            actor_user_id=triggered_by,
            target_entity="analysis_run",
            target_id=str(run.id),
            metadata={"batch_id": str(batch.id), **counts},
        )
        return {"run_id": str(run.id), **counts, "emails_sent": sent}

    except Exception as exc:  # noqa: BLE001 — persist failure state
        run.status = AnalysisStatus.FAILED
        run.error_message = f"{type(exc).__name__}: {str(exc)[:300]}"
        run.completed_at = datetime.now(UTC)
        await db.commit()
        raise
