import re
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.leaves import CompanyLeave
from app.models.uploads import ExtractedRow, UploadBatch, UploadedFile

log = get_logger("leaves")

MAX_RANGE_DAYS = 62
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


class LeaveRuleError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def parse_date(value) -> date | None:
    """Parses the date shapes people actually type (day-first, as used in
    India/Europe): 2026-07-17, 17-07-2026, 17/07/2026, 17.07.2026,
    17-Jul-2026, 17 July 2026, Jul 17 2026, Excel serials, ISO datetimes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{5}(\.0+)?", text):          # Excel serial day number
        serial = int(float(text))
        if 20000 < serial < 80000:
            return date(1899, 12, 30) + timedelta(days=serial)
    text = re.sub(r"[T ]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?Z?$", "", text)
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m:
        y, mo, d = map(int, m.groups())
        return _safe(y, mo, d)
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", text)
    if m:
        d, mo, y = map(int, m.groups())
        if mo > 12 and d <= 12:
            d, mo = mo, d                                # clearly month-first
        return _safe(y + 2000 if y < 100 else y, mo, d)
    m = re.fullmatch(r"(\d{1,2})[\s\-/.]*([A-Za-z]{3,9})[\s\-/.,]*(\d{2,4})", text)
    if m:
        d, mon, y = m.groups()
        mo = _MONTHS.get(mon[:3].lower())
        return _safe(int(y) + 2000 if len(y) == 2 else int(y), mo, int(d)) if mo else None
    m = re.fullmatch(r"([A-Za-z]{3,9})[\s\-/.]*(\d{1,2})[\s,\-/.]*(\d{4})", text)
    if m:
        mon, d, y = m.groups()
        mo = _MONTHS.get(mon[:3].lower())
        return _safe(int(y), mo, int(d)) if mo else None
    return None


def _safe(y: int, mo: int, d: int) -> date | None:
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def expand_row(values: dict) -> tuple[str, list[date], str | None]:
    """One register row → (employee_code, [dates], leave_type)."""
    code = str(values.get("employee_code") or "").strip()
    kind = (str(values.get("leave_type") or "").strip() or None)
    single = parse_date(values.get("leave_date"))
    if single:
        return code, [single], kind
    start, end = parse_date(values.get("from_date")), parse_date(values.get("to_date"))
    if start and not end:
        return code, [start], kind
    if start and end:
        if end < start:
            start, end = end, start
        span = (end - start).days
        if span > MAX_RANGE_DAYS:
            return code, [], kind
        return code, [start + timedelta(days=i) for i in range(span + 1)], kind
    return code, [], kind


async def _insert(db: AsyncSession, entries: list[dict]) -> int:
    if not entries:
        return 0
    stmt = insert(CompanyLeave).values(entries).on_conflict_do_nothing(
        constraint="uq_company_leaves_manager_code_date"
    ).returning(CompanyLeave.id)
    return len((await db.execute(stmt)).all())


async def import_leave_batch(db: AsyncSession, batch: UploadBatch) -> dict:
    from app.services.employee_service import validate_employee_code

    rows = (
        await db.execute(
            select(ExtractedRow.data)
            .join(UploadedFile, UploadedFile.id == ExtractedRow.file_id)
            .where(UploadedFile.batch_id == batch.id)
            .order_by(ExtractedRow.file_id, ExtractedRow.row_index)
        )
    ).scalars().all()
    entries, skipped = [], 0
    seen: set[tuple[str, date]] = set()
    for values in rows:
        code, dates, kind = expand_row(values or {})
        if not code or not validate_employee_code(code) or not dates:
            skipped += 1
            continue
        for d in dates:
            if (code, d) in seen:
                continue
            seen.add((code, d))
            entries.append({
                "manager_id": batch.manager_id, "employee_code": code, "leave_date": d,
                "leave_type": kind, "source": "UPLOAD", "batch_id": batch.id,
                "created_by": batch.manager_id,
            })
    inserted = 0
    for i in range(0, len(entries), 1000):
        inserted += await _insert(db, entries[i:i + 1000])
    await db.commit()
    log.info("leave_import", batch_id=str(batch.id), inserted=inserted, skipped=skipped)
    return {"inserted": inserted, "skipped": skipped}


async def add_leaves(db: AsyncSession, *, manager_id: uuid.UUID, actor_id: uuid.UUID,
                     employee_code: str, start: date, end: date | None,
                     leave_type: str | None) -> int:
    from app.services.employee_service import validate_employee_code

    code = employee_code.strip()
    if not validate_employee_code(code):
        raise LeaveRuleError(422, "bad_employee_code", "Employee ID format is invalid")
    end = end or start
    if end < start:
        raise LeaveRuleError(422, "bad_range", "End date is before start date")
    if (end - start).days > MAX_RANGE_DAYS:
        raise LeaveRuleError(422, "range_too_long", f"At most {MAX_RANGE_DAYS} days per entry")
    entries = [{
        "manager_id": manager_id, "employee_code": code,
        "leave_date": start + timedelta(days=i), "leave_type": leave_type,
        "source": "MANUAL", "created_by": actor_id,
    } for i in range((end - start).days + 1)]
    inserted = await _insert(db, entries)
    await db.commit()
    return inserted


async def delete_leave(db: AsyncSession, *, manager_id: uuid.UUID, leave_id: int) -> bool:
    result = await db.execute(
        delete(CompanyLeave)
        .where(CompanyLeave.id == leave_id, CompanyLeave.manager_id == manager_id)
        .returning(CompanyLeave.id)
    )
    await db.commit()
    return result.scalar_one_or_none() is not None


async def leave_lookup(db: AsyncSession, manager_id: uuid.UUID, codes: set[str],
                       start: date, end: date) -> dict[str, set[date]]:
    if not codes:
        return {}
    stmt = select(CompanyLeave.employee_code, CompanyLeave.leave_date).where(
        CompanyLeave.manager_id == manager_id,
        CompanyLeave.employee_code.in_(codes),
        CompanyLeave.leave_date.between(start, end),
    )
    out: dict[str, set[date]] = {}
    for code, d in (await db.execute(stmt)).all():
        out.setdefault(code.lower(), set()).add(d)
    return out
