"""company leave register routes: managers maintain their team's register, MA/EXEC read all, HR reads its manager's."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select

from app.api.deps import DB, require_role
from app.models.leaves import CompanyLeave
from app.models.user import User, UserRole
from app.schemas.business import LeaveCreate
from app.services import audit_service, leave_service

router = APIRouter(prefix="/leaves", tags=["leaves"])

Viewer = Annotated[
    User,
    Depends(require_role(UserRole.MASTER_ADMIN, UserRole.EXECUTIVE, UserRole.MANAGER, UserRole.HR)),
]
Manager = Annotated[User, Depends(require_role(UserRole.MANAGER))]


@router.get("")
async def list_leaves(
    actor: Viewer,
    db: DB,
    employee_code: str | None = Query(default=None, max_length=32),
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(CompanyLeave)
    if actor.role is UserRole.MANAGER:
        stmt = stmt.where(CompanyLeave.manager_id == actor.id)
    elif actor.role is UserRole.HR:
        if actor.manager_id is None:
            return {"items": [], "total": 0}
        stmt = stmt.where(CompanyLeave.manager_id == actor.manager_id)
    if employee_code:
        stmt = stmt.where(func.lower(CompanyLeave.employee_code) == employee_code.strip().lower())
    if month:
        from datetime import date, timedelta

        y, m = map(int, month.split("-"))
        if not 1 <= m <= 12:
            raise HTTPException(422, detail={"code": "bad_month", "message": "Month must be 01-12"})
        start = date(y, m, 1)
        end = (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)
        stmt = stmt.where(CompanyLeave.leave_date.between(start, end))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(CompanyLeave.leave_date.desc(), CompanyLeave.employee_code)
            .limit(limit).offset(offset)
        )
    ).scalars().all()
    return {"items": [r.public_dict() for r in rows], "total": int(total)}


@router.post("", status_code=201)
async def add_leave(body: LeaveCreate, actor: Manager, db: DB):
    start = leave_service.parse_date(body.start_date)
    end = leave_service.parse_date(body.end_date) if body.end_date else None
    if start is None or (body.end_date and end is None):
        raise HTTPException(422, detail={"code": "bad_date", "message": "Unrecognised date"})
    try:
        inserted = await leave_service.add_leaves(
            db, manager_id=actor.id, actor_id=actor.id, employee_code=body.employee_code,
            start=start, end=end, leave_type=body.leave_type,
        )
    except leave_service.LeaveRuleError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    await audit_service.record(
        db, action="ADD_COMPANY_LEAVE", result=audit_service.AuditResult.SUCCESS,
        actor_user_id=actor.id, target_entity="employee", target_id=body.employee_code,
        metadata={"start": start.isoformat(), "end": (end or start).isoformat(), "inserted": inserted},
    )
    return {"inserted": inserted}


@router.delete("/{leave_id}", status_code=204, response_class=Response)
async def remove_leave(leave_id: int, actor: Manager, db: DB) -> Response:
    if not await leave_service.delete_leave(db, manager_id=actor.id, leave_id=leave_id):
        raise HTTPException(404, detail={"code": "not_found", "message": "Leave entry not found"})
    await audit_service.record(
        db, action="DELETE_COMPANY_LEAVE", result=audit_service.AuditResult.SUCCESS,
        actor_user_id=actor.id, target_entity="company_leave", target_id=str(leave_id),
    )
    return Response(status_code=204)
