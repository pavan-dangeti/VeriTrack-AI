"""Employee repository routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import DB, require_role
from app.models.user import User, UserRole
from app.schemas.business import EmployeeFieldUpdate
from app.services import employee_service

router = APIRouter(prefix="/employees", tags=["employees"])

RepoViewer = Annotated[
    User,
    Depends(require_role(UserRole.MASTER_ADMIN, UserRole.EXECUTIVE, UserRole.MANAGER, UserRole.HR)),
]
Editor = Annotated[User, Depends(require_role(UserRole.MANAGER))]


def _serialize(emp) -> dict:
    v = emp.current_version
    return {
        "id": str(emp.id),
        "manager_id": str(emp.manager_id),
        "employee_code": emp.employee_code,
        "full_name": v.full_name if v else "",
        "official_email": v.official_email if v else None,
        "personal_email": v.personal_email if v else None,
        "department": v.department if v else None,
        "updated_at": emp.updated_at.isoformat() if emp.updated_at else None,
    }


@router.get("")
async def list_employees(actor: RepoViewer, db: DB):
    employees = await employee_service.list_scoped(db, actor)
    return {"items": [_serialize(e) for e in employees],
            "total": len(employees)}


@router.patch("/{employee_id}")
async def correct_employee(
    employee_id: uuid.UUID,
    body: EmployeeFieldUpdate,
    actor: Editor,
    db: DB,
):
    """Inline single-field correction — creates a new version, keeps history."""
    updates = {k: v for k, v in body.model_dump().items() if k != "note" and v is not None}
    if not updates:
        raise HTTPException(
            400, detail={"code": "no_changes", "message": "No fields to update"}
        )
    try:
        version = await employee_service.apply_correction(
            db, actor=actor, employee_id=employee_id,
            field_updates=updates, note=body.note,
        )
    except employee_service.EmployeeRuleError as exc:
        raise HTTPException(
            exc.status_code, detail={"code": exc.code, "message": exc.message}
        ) from exc
    return version.public_dict()


@router.get("/{employee_id}/history")
async def employee_history(employee_id: uuid.UUID, actor: RepoViewer, db: DB):
    try:
        versions = await employee_service.get_history(db, actor, employee_id)
    except employee_service.EmployeeRuleError as exc:
        raise HTTPException(
            exc.status_code, detail={"code": exc.code, "message": exc.message}
        ) from exc
    return {"items": [v.public_dict() for v in versions]}
