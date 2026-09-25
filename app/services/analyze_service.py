"""Analysis orchestration: run the GETS rules over a batch, persist deduped violations, email, report."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
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


async def _analyze_timesheets(db, run, batch, rows, repo, counts, skip_log, seen_codes) -> None:
    """GETS screenshots: per employee, every 'Out Of Office' day (customer
    leave) must exist in the company leave register for that date."""
    from app.services.employee_service import validate_employee_code
    from app.services.leave_service import leave_lookup

    per_emp: dict[str, dict] = {}
    for row in rows:
        values = row.data or {}
        code = str(values.get("employee_code") or "").strip()
        extra = values.get("extra") or {}
        if not code and not extra.get("project_id"):
            continue  # a sheet-native summary line
        entry = per_emp.setdefault(code.lower(), {
            "code": code, "dates": set(), "review": [], "name": values.get("full_name"),
            "periods": set(),
        })
        entry["dates"].update(gets_rules.customer_leave_dates(values))
        if extra.get("period"):
            entry["periods"].add(extra["period"])
        if row.needs_review:
            entry["review"].append(row.review_note or "flagged for review")

    all_dates = [d for e in per_emp.values() for d in e["dates"]]
    register = {}
    if all_dates:
        register = await leave_lookup(
            db, batch.manager_id, {e["code"] for e in per_emp.values() if e["code"]},
            min(all_dates), max(all_dates),
        )

    for key, e in per_emp.items():
        code = e["code"]
        if not code or not validate_employee_code(code):
            counts["skipped"] += 1
            skip_log.append({"status": "BAD_ID_FORMAT", "employee_code": code[:64]})
            continue
        record = repo.get(key)
        if record is None:
            counts["skipped"] += 1
            skip_log.append({"status": "NOT_IN_REPO", "employee_code": code,
                             "reason": "Employee ID not found in manager's repository"})
            continue
        if e["review"]:
            # never email anyone on an extraction a human has not confirmed
            counts["skipped"] += 1
            skip_log.append({"status": "NEEDS_REVIEW", "employee_code": code,
                             "reason": e["review"][0][:200]})
            continue
        counts["rows_processed"] += 1
        counts["matched"] += 1
        recorded = register.get(key, set())
        violation, reason, missing = gets_rules.evaluate_timesheet_leave(e["dates"], recorded)
        if not violation or key in seen_codes:
            continue
        seen_codes.add(key)
        counts["violations"] += 1
        email_to = gets_rules.resolve_email(
            official=record.get("official_email"), personal=record.get("personal_email")
        )
        db.add(ViolationResult(
            run_id=run.id,
            manager_id=batch.manager_id,
            employee_code=code,
            employee_name=record.get("full_name") or e["name"],
            customer_leave_value=", ".join(d.isoformat() for d in sorted(e["dates"])),
            company_leave_value=", ".join(d.isoformat() for d in sorted(recorded & e["dates"])),
            violation_reason=reason,
            email_to=email_to,
            email_status=EmailStatus.PENDING if email_to else EmailStatus.SKIPPED_NO_EMAIL,
            details={
                "source": "GETS_TIMESHEET",
                "periods": sorted(e["periods"]),
                "customer_leave_dates": [d.isoformat() for d in sorted(e["dates"])],
                "missing_in_register": [d.isoformat() for d in missing],
            },
        ))


async def precheck_analysis(db: AsyncSession, batch: UploadBatch) -> None:
    if batch.kind is not BatchKind.GETS:
        raise AnalyzeRuleError(400, "wrong_kind", "Analyze runs on GETS batches only")
    if batch.status not in (BatchStatus.COMPLETED, BatchStatus.FAILED):
        raise AnalyzeRuleError(409, "not_ready", "Batch processing has not completed yet")
    existing = (
        await db.execute(select(AnalysisRun.id).where(AnalysisRun.batch_id == batch.id))
    ).scalar_one_or_none()
    if existing is not None:
        raise AnalyzeRuleError(409, "already_analyzed", "This batch was already analyzed")


async def claim_analysis(db: AsyncSession, batch: UploadBatch, triggered_by=None) -> AnalysisRun:
    """Creates the RUNNING run row; the unique batch_id makes this the one
    atomic claim, so concurrent triggers get a 409 instead of a second job."""
    await precheck_analysis(db, batch)
    run = AnalysisRun(
        batch_id=batch.id,
        manager_id=batch.manager_id,
        triggered_by=triggered_by,
        status=AnalysisStatus.RUNNING,
    )
    db.add(run)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AnalyzeRuleError(409, "already_analyzed", "This batch was already analyzed") from exc
    return run


async def execute_analysis(db: AsyncSession, batch_id: str, triggered_by=None, run_id=None) -> dict:
    batch = await db.get(UploadBatch, uuid.UUID(batch_id))
    if batch is None:
        raise AnalyzeRuleError(404, "not_found", "Batch not found")
    if run_id is None:
        run = await claim_analysis(db, batch, triggered_by)
    else:
        run = await db.get(AnalysisRun, uuid.UUID(str(run_id)))
        if run is None or run.status is not AnalysisStatus.RUNNING:
            raise AnalyzeRuleError(409, "already_analyzed", "This batch was already analyzed")
        await db.execute(delete(ViolationResult).where(ViolationResult.run_id == run.id))
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
        timesheet_rows = [r for r in rows if gets_rules.is_timesheet_row(r.data or {})]
        rows = [r for r in rows if not gets_rules.is_timesheet_row(r.data or {})]

        await _analyze_timesheets(
            db, run, batch, timesheet_rows, repo, counts, skip_log, seen_codes
        )

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

            # Dedup: one result row (and one email) per employee per run.
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
                    company_leave_value=payload.get("company_leave_value"),
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
