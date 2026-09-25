from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DB, require_role
from app.core.config import settings
from app.models.analysis import AnalysisRun, AnalysisStatus, EmailStatus, ViolationResult
from app.models.employees import Employee
from app.models.m365_domain import ApprovedM365Domain
from app.models.uploads import UploadBatch
from app.models.user import User, UserRole

router = APIRouter(tags=["dashboard", "settings"])

AnyAuthenticated = Annotated[
    User,
    Depends(
        require_role(
            UserRole.MASTER_ADMIN,
            UserRole.EXECUTIVE,
            UserRole.MANAGER,
            UserRole.HR,
        )
    ),
]
MasterAdminOnly = Annotated[User, Depends(require_role(UserRole.MASTER_ADMIN))]


async def _counts(db, stmt) -> int:
    return int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())


@router.get("/dashboard/summary")
async def dashboard_summary(actor: AnyAuthenticated, db: DB) -> dict[str, Any]:
    """One payload per role — the frontend renders from this, never guesses."""
    exec_view = actor.role in (UserRole.MASTER_ADMIN, UserRole.EXECUTIVE)
    scope_note = "all managers" if exec_view else "your workspace"

    employee_base = select(Employee).where(Employee.is_deleted.is_(False))
    batch_base = select(UploadBatch)
    run_base = select(AnalysisRun)
    if not exec_view:
        owner = actor.id if actor.role is UserRole.MANAGER else actor.manager_id
        employee_base = employee_base.where(Employee.manager_id == owner)
        batch_base = batch_base.where(UploadBatch.manager_id == owner)
        run_base = run_base.where(AnalysisRun.manager_id == owner)

    employees_total = await _counts(db, employee_base)
    employees_flagged = await _counts(db, employee_base.where(Employee.needs_review.is_(True)))
    batches_total = await _counts(db, batch_base)
    runs_completed = await _counts(db, run_base.where(AnalysisRun.status == AnalysisStatus.COMPLETED))

    violations = emails_sent = 0
    if actor.role is not UserRole.HR:
        v_stmt = (
            select(func.count())
            .select_from(ViolationResult)
            .join(AnalysisRun, AnalysisRun.id == ViolationResult.run_id)
        )
        if actor.role is UserRole.MANAGER:
            v_stmt = v_stmt.where(AnalysisRun.manager_id == actor.id)
        violations = int((await db.execute(v_stmt)).scalar_one())
        s_stmt = v_stmt.where(ViolationResult.email_status == EmailStatus.SENT)
        emails_sent = int((await db.execute(s_stmt)).scalar_one())

    payload: dict[str, Any] = {
        "role": actor.role.value,
        "scope": scope_note,
        "employees_total": employees_total,
        "employees_needing_review": employees_flagged,
        "batches_total": batches_total,
        "analysis_runs_completed": runs_completed,
    }
    if actor.role is not UserRole.HR:
        payload["violations_detected"] = violations
        payload["emails_sent"] = emails_sent
    if exec_view:
        payload["users_by_role"] = {
            role.value: await _counts(
                db,
                select(User).where(User.role == role, User.is_active.is_(True)),
            )
            for role in UserRole
        }
    if actor.role is UserRole.HR:
        latest = (
            await db.execute(
                select(UploadBatch)
                .where(
                    UploadBatch.kind == "GETS",
                    UploadBatch.manager_id == actor.manager_id,
                )
                .order_by(UploadBatch.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        payload["latest_gets_batch"] = (
            {"id": str(latest.id), "status": latest.status.value,
             "created_at": latest.created_at.isoformat()}
            if latest else None
        )
    return payload


@router.get("/settings")
async def get_settings(actor: MasterAdminOnly):
    return {"retention_days": settings.retention_days}


@router.post("/settings/purge-obsolete-data")
async def purge_obsolete_data(actor: MasterAdminOnly, db: DB):
    """Deletes GETS batches/reports past the retention window; employee records are never touched."""
    from app.services import batch_service

    return await batch_service.purge_obsolete_batches(
        db, actor=actor, retention_days=settings.retention_days
    )


class DomainIn(BaseModel):
    domain: str


@router.get("/settings/m365-domains")
async def list_domains(actor: MasterAdminOnly, db: DB):
    stmt = select(ApprovedM365Domain).order_by(ApprovedM365Domain.domain)
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [{"domain": r.domain, "is_active": r.is_active} for r in rows]}


@router.post("/settings/m365-domains", status_code=201)
async def approve_domain(body: DomainIn, actor: MasterAdminOnly, db: DB):

    domain = body.domain.strip().lower().lstrip("@")
    if "." not in domain or " " in domain or "@" in domain:
        raise HTTPException(
            422,
            detail={"code": "bad_domain",
                    "message": "Enter a valid domain like corp.io"},
        )
    existing = (
        await db.execute(select(ApprovedM365Domain).where(ApprovedM365Domain.domain == domain))
    ).scalar_one_or_none()
    if existing:
        existing.is_active = True
    else:
        db.add(ApprovedM365Domain(domain=domain, created_by=actor.id))
    await db.commit()
    return {"domain": domain, "is_active": True}
