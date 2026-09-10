"""Analytics aggregation: time series + manager breakdown for the Analytics page.

Scoping mirrors the rest of the API: MA/EXEC see everything, MANAGER sees
their own workspace, HR is rejected by the role guard (no listing access).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.deps import DB, require_role
from app.models.analysis import AnalysisRun
from app.models.uploads import UploadBatch
from app.models.user import User, UserRole

router = APIRouter(prefix="/analytics", tags=["analytics"])

Viewer = Annotated[
    User,
    Depends(
        require_role(
            UserRole.MASTER_ADMIN, UserRole.EXECUTIVE, UserRole.MANAGER, UserRole.HR
        )
    ),
]


def _month(row_column):
    """Calendar-month bucket in UTC, independent of the DB session timezone."""
    return func.date_trunc("month", func.timezone("UTC", row_column))


@router.get("/summary")
async def analytics_summary(actor: Viewer, db: DB):
    # Scope: MANAGER -> own id; HR -> their manager's id; MA/EXEC -> everything.
    scoped_owner_id = None
    if actor.role is UserRole.MANAGER:
        scoped_owner_id = actor.id
    elif actor.role is UserRole.HR:
        scoped_owner_id = actor.manager_id
    scoped = scoped_owner_id is not None

    runs = select(
        _month(AnalysisRun.started_at).label("month"),
        func.sum(AnalysisRun.violations).label("violations"),
        func.sum(AnalysisRun.rows_processed).label("rows_processed"),
        func.sum(AnalysisRun.matched).label("matched"),
        func.sum(AnalysisRun.files_processed).label("files_processed"),
        func.sum(AnalysisRun.emails_sent).label("emails_sent"),
        func.sum(AnalysisRun.emails_missing).label("emails_missing"),
        func.sum(AnalysisRun.emails_errored).label("emails_errored"),
        func.sum(AnalysisRun.skipped).label("skipped"),
    ).group_by("month")
    if scoped:
        runs = runs.where(AnalysisRun.manager_id == scoped_owner_id)
    run_rows = (await db.execute(runs)).all()

    uploads = select(
        _month(UploadBatch.created_at).label("month"),
        func.count().label("batches"),
        func.sum(UploadBatch.processed_files).label("files_processed"),
    ).group_by("month")
    if scoped:
        uploads = uploads.where(UploadBatch.manager_id == scoped_owner_id)
    upload_rows = (await db.execute(uploads)).all()

    # Merge both sources into one month-keyed table
    months: dict[str, dict] = {}

    def _entry(month) -> dict:
        key = month.strftime("%Y-%m")
        return months.setdefault(key, {
            "month": key, "violations": 0, "rows_processed": 0, "matched": 0,
            "batches": 0, "files_processed": 0,
        })

    for r in run_rows:
        e = _entry(r.month)
        e["violations"] += r.violations or 0
        e["rows_processed"] += r.rows_processed or 0
        e["matched"] += r.matched or 0
        e["files_processed"] += r.files_processed or 0
    for u in upload_rows:
        e = _entry(u.month)
        e["batches"] += u.batches or 0
        e["files_processed"] += u.files_processed or 0

    payload: dict = {
        "scoped_to_self": scoped,
        "monthly": [months[k] for k in sorted(months)],
        "emails": {
            "sent": sum(r.emails_sent or 0 for r in run_rows),
            "missing": sum(r.emails_missing or 0 for r in run_rows),
            "errored": sum(r.emails_errored or 0 for r in run_rows),
            "skipped": sum(r.skipped or 0 for r in run_rows),
        },
    }

    if not scoped:
        per_manager = (
            select(
                User.id, User.email, User.full_name,
                func.coalesce(func.sum(AnalysisRun.violations), 0).label("violations"),
                func.count(func.distinct(AnalysisRun.id)).label("runs"),
            )
            .join(AnalysisRun, AnalysisRun.manager_id == User.id)
            .group_by(User.id)
            .order_by(func.sum(AnalysisRun.violations).desc())
        )
        rows = (await db.execute(per_manager)).all()
        # uploads per manager (separate grouping to avoid fan-out double count)
        up_rows = (
            await db.execute(
                select(UploadBatch.manager_id, func.count().label("batches"))
                .group_by(UploadBatch.manager_id)
            )
        ).all()
        batches_by_mgr = {str(r.manager_id): r.batches for r in up_rows}
        payload["by_manager"] = [
            {
                "manager_id": str(r.id),
                "manager_name": r.full_name or r.email,
                "manager_email": r.email,
                "violations": r.violations,
                "runs": r.runs,
                "batches": batches_by_mgr.get(str(r.id), 0),
            }
            for r in rows
        ]
    return payload
