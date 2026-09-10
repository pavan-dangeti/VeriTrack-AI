"""Employee repository service: bulk upsert from batches + inline corrections."""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.employees import Employee, EmployeeVersion
from app.models.user import User
from app.services import audit_service


class EmployeeRuleError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def validate_employee_code(code: str) -> bool:
    return bool(re.match(settings.employee_id_pattern, code or ""))


async def _next_version_no(db: AsyncSession, employee_id) -> int:
    stmt = (
        select(EmployeeVersion.version_no)
        .where(EmployeeVersion.employee_id == employee_id)
        .order_by(EmployeeVersion.version_no.desc())
        .limit(1)
    )
    latest = (await db.execute(stmt)).scalar_one_or_none()
    return (latest or 0) + 1


async def _insert_version(
    db: AsyncSession,
    *,
    employee: Employee,
    values: dict,
    changed_by,
    source: str,
    note: str | None = None,
) -> EmployeeVersion:
    version = EmployeeVersion(
        employee_id=employee.id,
        version_no=await _next_version_no(db, employee.id),
        full_name=str(values.get("full_name") or "").strip(),
        official_email=values.get("official_email"),
        personal_email=values.get("personal_email"),
        department=values.get("department"),
        changed_by=changed_by,
        change_source=source,
        change_note=note,
    )
    db.add(version)
    await db.flush()
    employee.current_version_id = version.id
    employee.updated_at = version.created_at
    return version


async def upsert_from_extracted_rows(
    db: AsyncSession,
    *,
    manager_id,
    rows_by_code: dict[str, dict],  # code -> best normalized values
    actor_id=None,
    review_by_code: dict[str, dict] | None = None,  # code -> {needs_review, note, confidence}
) -> tuple[int, int]:
    review_by_code = review_by_code or {}
    """Bulk import from an EMPLOYEE_REPO batch. Re-upload updates in place by
    inserting new versions — history is never lost."""
    created = updated = 0
    seen_lower: set[str] = set()
    for code, values in rows_by_code.items():
        if not validate_employee_code(code):
            continue
        if not str(values.get("full_name") or "").strip():
            continue
        if code.lower() in seen_lower:
            continue  # same code twice within one import: first wins
        seen_lower.add(code.lower())
        stmt = select(Employee).where(
            Employee.manager_id == manager_id,
            Employee.employee_code == code,
            Employee.is_deleted.is_(False),
        )
        employee = (await db.execute(stmt)).scalar_one_or_none()
        review = review_by_code.get(code.lower(), {})
        if employee is None:
            employee = Employee(
                manager_id=manager_id,
                employee_code=code,
                needs_review=bool(review.get("needs_review")),
                review_note=review.get("note"),
                ocr_confidence=review.get("confidence"),
            )
            db.add(employee)
            await db.flush()
            await _insert_version(
                db, employee=employee, values=values, changed_by=actor_id, source="UPLOAD"
            )
            created += 1
        else:
            current = await db.get(EmployeeVersion, employee.current_version_id)
            changed = current is not None and any(
                (getattr(current, f) or None) != (values.get(f) or None)
                for f in EDITABLE_FIELDS
            )
            if changed:
                await _insert_version(
                    db,
                    employee=employee,
                    values=values,
                    changed_by=actor_id,
                    source="UPLOAD",
                    note="re-upload changed fields",
                )
                updated += 1
            # Even unchanged rows can newly carry a review flag from a re-scan.
            employee.needs_review = bool(review.get("needs_review"))
            employee.review_note = review.get("note")
            employee.ocr_confidence = review.get("confidence")
    await db.commit()
    return created, updated


EDITABLE_FIELDS = ("full_name", "official_email", "personal_email", "department")


async def apply_correction(
    db: AsyncSession,
    *,
    actor: User,
    employee_id,
    field_updates: dict[str, str | None],
    note: str | None = None,
) -> EmployeeVersion:
    stmt = select(Employee).where(
        Employee.id == employee_id,
        Employee.manager_id == actor.id,  # managers edit only their own repo
        Employee.is_deleted.is_(False),
    )
    employee = (await db.execute(stmt)).scalar_one_or_none()
    if employee is None:
        raise EmployeeRuleError(404, "not_found", "Employee not found in your repository")

    unknown = set(field_updates) - set(EDITABLE_FIELDS)
    if unknown:
        raise EmployeeRuleError(400, "bad_fields", f"Not editable: {sorted(unknown)}")

    current = await db.get(EmployeeVersion, employee.current_version_id)
    values = {
        "full_name": current.full_name,
        "official_email": current.official_email,
        "personal_email": current.personal_email,
        "department": current.department,
    }
    for field, value in field_updates.items():
        if field in ("official_email", "personal_email") and value:
            from app.services.extraction.normalize import normalize_email

            value = normalize_email(value)
            if value is None:
                raise EmployeeRuleError(422, "bad_email", f"'{field}' is not a valid email")
        values[field] = (value or "").strip() if isinstance(value, str) else value

    if not str(values["full_name"]).strip():
        raise EmployeeRuleError(422, "name_required", "full_name cannot be empty")

    version = await _insert_version(
        db,
        employee=employee,
        values=values,
        changed_by=actor.id,
        source="CORRECTION",
        note=note or f"inline edit: {sorted(field_updates)}",
    )
    # A human has spoken — clear the OCR review flag.
    employee.needs_review = False
    employee.review_note = None
    await db.commit()

    await audit_service.record(
        db,
        action="CORRECT_EMPLOYEE",
        result=audit_service.AuditResult.SUCCESS,
        actor_user_id=actor.id,
        target_entity="employee",
        target_id=str(employee.id),
        metadata={"fields": sorted(field_updates), "version": version.version_no},
    )
    return version


async def list_scoped(db: AsyncSession, actor: User) -> list[Employee]:
    """Query-layer scoping: MANAGER sees own; MA/EXEC see all; HR sees their
    manager's repository."""
    from app.models.user import UserRole

    base = (
        select(Employee)
        .where(Employee.is_deleted.is_(False))
        .order_by(Employee.employee_code)
    )
    if actor.role is UserRole.MANAGER:
        return list((await db.execute(base.where(Employee.manager_id == actor.id))).scalars())
    if actor.role is UserRole.HR:
        if actor.manager_id is None:
            return []
        return list(
            (await db.execute(base.where(Employee.manager_id == actor.manager_id))).scalars()
        )
    # MASTER_ADMIN / EXECUTIVE view everything
    return list((await db.execute(base)).scalars())


async def _get_visible_employee_or_raise(db: AsyncSession, actor: User, employee_id):
    employee = await db.get(Employee, employee_id)
    if employee is None or employee.is_deleted:
        raise EmployeeRuleError(404, "not_found", "Employee not found")
    visible_ids = {e.id for e in await list_scoped(db, actor)}
    if employee.id not in visible_ids:
        raise EmployeeRuleError(403, "forbidden", "Not in your visible scope")
    return employee


async def get_history(db: AsyncSession, actor: User, employee_id) -> list[EmployeeVersion]:
    employee = await _get_visible_employee_or_raise(db, actor, employee_id)
    stmt = (
        select(EmployeeVersion)
        .where(EmployeeVersion.employee_id == employee.id)
        .order_by(EmployeeVersion.version_no.desc())
    )
    return list((await db.execute(stmt)).scalars())


async def get_detail(db: AsyncSession, actor: User, employee_id):
    """Full record + version history + GETS batches this code appeared in."""
    from app.models.uploads import BatchKind, ExtractedRow, UploadBatch, UploadedFile

    employee = await _get_visible_employee_or_raise(db, actor, employee_id)
    versions = await get_history(db, actor, employee_id)
    batches = (
        await db.execute(
            select(UploadBatch)
            .join(UploadedFile, UploadedFile.batch_id == UploadBatch.id)
            .join(ExtractedRow, ExtractedRow.file_id == UploadedFile.id)
            .where(
                UploadBatch.kind == BatchKind.GETS,
                UploadBatch.manager_id == employee.manager_id,
                ExtractedRow.data["employee_code"].astext == employee.employee_code,
            )
            .distinct()
            .order_by(UploadBatch.created_at.desc())
            .limit(20)
        )
    ).scalars()
    return employee, versions, list(batches)
