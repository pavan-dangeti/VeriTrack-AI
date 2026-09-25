"""Normalization layer: any source -> one internal record format.

Column aliases match case/whitespace-insensitively, so messy headers like "  Customer Leave " or
"EMP CODE" normalize. Unrecognised columns are preserved under data["extra"].
"""

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    # canonical name included in its own aliases (OCR fallback emits canonical)
    "employee_code": ("employee_code", "employee id", "employee code", "emp id",
                      "emp code", "code", "id"),
    "full_name": ("full_name", "full name", "employee name", "emp name", "name"),
    "official_email": (
        "official_email", "official email", "company email", "work email",
        "office email", "email",
    ),
    "personal_email": ("personal_email", "personal email", "private email",
                       "personal mail"),
    "department": ("department", "dept", "team"),
}

LEAVE_COLUMN_ALIASES = {
    "customer_leave": ("customer leave",),
    "company_leave": ("company leave", "internal leave", "register leave"),
}
# exports label the company-side column with the organisation's name, e.g. "<Org> Leave"
_ORG_LEAVE = re.compile(r"^(?!customer\b)[a-z][a-z0-9&.]*(?: [a-z0-9&.]+)? leave$")
_NOT_A_TICK = {"leave type", "leave date", "annual leave", "sick leave", "casual leave", "earned leave"}


def is_leave_column(header: str) -> bool:
    h = _norm_header(header)
    return h == "customer leave" or (h not in _NOT_A_TICK and bool(_ORG_LEAVE.match(h)))


@dataclass
class NormalizedRow:
    values: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    needs_review: bool = False
    review_note: str | None = None

    @property
    def employee_code(self) -> str:
        return str(self.values.get("employee_code") or "").strip()

    @property
    def full_name(self) -> str:
        return str(self.values.get("full_name") or "").strip()


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", str(h or "")).strip().lower()


def build_header_map(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    normalized = {_norm_header(h): h for h in headers}
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[canonical] = normalized[alias]
                break
    for canonical, aliases in LEAVE_COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[canonical] = normalized[alias]
                break
    if "company_leave" not in mapping:
        org = [raw for norm, raw in normalized.items() if norm != "customer leave" and is_leave_column(norm)]
        if len(org) == 1:
            mapping["company_leave"] = org[0]
    return mapping


def has_required_columns(headers: list[str]) -> bool:
    m = build_header_map(headers)
    return "employee_code" in m and "full_name" in m


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text or text in {"-", "--", "n/a", "na", "none", "null"}:
        return None
    if not EMAIL_RE.match(text):
        return None
    return text


def normalize_row(
    headers: list[str],
    raw_cells: list[Any],
    confidence: float | None = None,
) -> NormalizedRow:
    mapping = build_header_map(headers)
    cell_by_header = {
        _norm_header(h): (raw_cells[i] if i < len(raw_cells) else "")
        for i, h in enumerate(headers)
    }

    values: dict[str, Any] = {}
    for canonical, header in mapping.items():
        raw_value = cell_by_header.get(_norm_header(header), "")
        text = str(raw_value if raw_value is not None else "").strip()
        if canonical in ("official_email", "personal_email"):
            values[canonical] = normalize_email(text)
        else:
            values[canonical] = text

    known = {v for v in mapping.values()}
    extras = {
        _norm_header(h): str(cell_by_header[_norm_header(h)] or "").strip()
        for h in headers
        if h and h not in known
    }
    if extras:
        values["extra"] = {k: v for k, v in extras.items() if v != ""}

    row = NormalizedRow(values=values, confidence=confidence)
    if confidence is not None and confidence < settings.low_confidence_threshold:
        row.needs_review = True
        row.review_note = f"low OCR confidence ({confidence:.2f})"
    return row


GETS_DAY_RE = re.compile(r"^(?:day\s*)?(\d{1,2})(?:\s*\(\w{2}\))?\s*$", re.IGNORECASE)

GETS_ALIASES: dict[str, tuple[str, ...]] = {
    "employee_code": ("employee_code", "person id", "personid", "employee id", "emp id"),
    "full_name": ("full_name", "employee name", "name"),
    "supplier": ("supplier",),
    "job_family": ("job_family", "billable job family", "job family"),
    "hour_type": ("hour_type", "uom", "hour type"),
    "project_id": ("project_id", "project id"),
    "project_name": ("project_name", "sub project", "subproject"),
    "task_id": ("task_id", "sub project id", "subproject id"),
    "remarks": ("remarks", "remark"),
    "total": ("total",),
}


def _is_day_header(h) -> int | None:
    m = GETS_DAY_RE.match(str(h or "").strip())
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 31 else None


def is_gets_table(headers: list[str]) -> bool:
    """Timesheet layout: a run of day-numbered columns marks a GETS sheet."""
    return sum(1 for h in headers if _is_day_header(h)) >= 20


def _num(text: str) -> float | None:
    try:
        value = float(str(text).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else value


def _gets_values(mapping: dict[str, str], day_hours: dict[int, float | None]) -> dict[str, Any]:
    code = re.sub(r"\s+", "", mapping.get("employee_code", ""))
    m = re.match(r"^(\d{3,})", code)
    extra: dict[str, Any] = {
        "supplier": mapping.get("supplier", ""),
        "job_family": mapping.get("job_family", ""),
        "hour_type": mapping.get("hour_type", "").upper(),
        "project_id": mapping.get("project_id", ""),
        "project_name": mapping.get("project_name", ""),
        "task_id": mapping.get("task_id", ""),
        "remarks": mapping.get("remarks", ""),
    }
    for d, v in sorted(day_hours.items()):
        if v is not None:
            extra[f"day_{d:02d}"] = v
    total = _num(mapping.get("total", ""))
    if total is not None:
        extra["total"] = total
    ooo = "outofoffice" in re.sub(r"[^a-z]", "", extra["project_name"].lower())
    extra["is_out_of_office"] = ooo
    if ooo:
        extra["leave_days"] = [d for d, v in sorted(day_hours.items()) if v]
    return {
        "employee_code": m.group(1) if m else code,
        "full_name": mapping.get("full_name", ""),
        "extra": {k: v for k, v in extra.items() if v not in ("", None)},
    }


def _review_gets(row: NormalizedRow) -> NormalizedRow:
    code = row.employee_code
    name = row.full_name.lower()
    is_summary = (not code) and ("total" in name or name == "")
    if is_summary:
        row.needs_review = False
    elif not re.fullmatch(r"\d{3,}", code):
        row.needs_review = True
        row.review_note = "employee code unreadable"
    elif row.confidence is not None and row.confidence < 0.5:
        row.needs_review = True
        row.review_note = f"low OCR confidence ({row.confidence:.2f})"
    return row


def normalize_gets_row(
    headers: list[str], raw_cells: list[Any], confidence: float | None = None
) -> NormalizedRow:
    """Spreadsheet/CSV GETS exports: columns matched by name, day columns by
    number ('1'..'31' or 'Day 1')."""
    cells = [str(c if c is not None else "").strip() for c in raw_cells]
    mapping: dict[str, str] = {}
    day_hours: dict[int, float | None] = {}
    for i, h in enumerate(headers):
        value = cells[i] if i < len(cells) else ""
        day = _is_day_header(h)
        if day:
            day_hours[day] = _num(value) if value else None
            continue
        hn = _norm_header(h)
        for key, aliases in GETS_ALIASES.items():
            if hn in aliases and key not in mapping:
                mapping[key] = value
                break
    return _review_gets(NormalizedRow(values=_gets_values(mapping, day_hours), confidence=confidence))


def normalize_gets_sheet(sheet: dict) -> list[NormalizedRow]:
    rows: list[NormalizedRow] = []
    period = sheet.get("period")
    for line in sheet.get("lines", []):
        cells = line.get("cells", [])
        day_hours = {c["day"]: c["hours"] for c in cells if c.get("hours") is not None}
        mapping = {
            "employee_code": line.get("person_id") or sheet.get("person_id", ""),
            "full_name": sheet.get("employee_name", ""),
            "supplier": line.get("supplier", ""),
            "job_family": line.get("job_family", ""),
            "hour_type": line.get("uom", ""),
            "project_id": line.get("project_id", ""),
            "project_name": line.get("sub_project", ""),
            "task_id": line.get("sub_project_id", ""),
            "remarks": line.get("remarks", ""),
            "total": str(line.get("printed_total") if line.get("printed_total") is not None
                         else line.get("computed_total", "")),
        }
        values = _gets_values(mapping, day_hours)
        values["extra"]["day_status"] = {
            str(c["day"]): c["status"] for c in cells if c.get("hours") is not None
        }
        if period:
            values["extra"]["period"] = period
        row = _review_gets(NormalizedRow(values=values, confidence=line.get("confidence")))
        issues = list(line.get("issues") or [])
        if sheet.get("verified"):
            # every row sum and per-day total reconciles, so a hesitant read
            # of a single digit is already proven by the arithmetic
            issues = [i for i in issues if "low-confidence read" not in i]
        else:
            failed = [c["check"] for c in sheet.get("checks", []) if not c.get("ok")]
            issues.append("totals cross-check failed: " + "; ".join(failed[:3]))
        if issues and not row.needs_review:
            row.needs_review = True
            row.review_note = "; ".join(issues)[:400]
        rows.append(row)
    return rows


LEAVE_REGISTER_ALIASES: dict[str, tuple[str, ...]] = {
    "leave_date": ("leave date", "date", "leave_date", "day", "leave day"),
    "from_date": ("from", "from date", "start date", "start", "leave from", "from_date"),
    "to_date": ("to", "to date", "end date", "end", "leave to", "till", "to_date"),
    "leave_type": ("leave type", "type", "leave_type", "category", "reason"),
}


def leave_register_map(headers: list[str]) -> dict[str, str] | None:
    """Canonical key -> header for leave registers (needs an ID and a date)."""
    base = build_header_map(headers)
    if "employee_code" not in base:
        for h in headers:
            if _norm_header(h) in ("person id", "personid", "employee number", "emp no", "emp number"):
                base["employee_code"] = h
                break
    if "employee_code" not in base:
        return None
    mapping = {"employee_code": base["employee_code"]}
    normalized = {_norm_header(h): h for h in headers}
    for key, aliases in LEAVE_REGISTER_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[key] = normalized[alias]
                break
    if "leave_date" not in mapping and "from_date" not in mapping:
        return None
    return mapping


def normalize_leave_row(mapping: dict[str, str], headers: list[str], cells: list[Any]) -> NormalizedRow:
    by_header = {h: (str(cells[i]).strip() if i < len(cells) and cells[i] is not None else "")
                 for i, h in enumerate(headers)}
    values = {key: by_header.get(header, "") for key, header in mapping.items()}
    values["record_type"] = "leave"
    return NormalizedRow(values=values)


def normalize_tables(tables, *, kind: str | None = None) -> list[NormalizedRow]:
    rows: list[NormalizedRow] = []
    for table in tables:
        sheet = (getattr(table, "meta", None) or {}).get("gets_sheet")
        if sheet:
            rows.extend(normalize_gets_sheet(sheet))
            continue
        if not table.headers:
            continue
        confs = getattr(table, "row_confidences", None) or []
        if kind == "COMPANY_LEAVE":
            mapping = leave_register_map(list(table.headers))
            if mapping:
                rows.extend(normalize_leave_row(mapping, list(table.headers), cells)
                            for cells in table.rows)
            continue
        if is_gets_table(table.headers):
            for idx, cells in enumerate(table.rows):
                confidence = confs[idx] if idx < len(confs) else None
                rows.append(normalize_gets_row(table.headers, cells, confidence))
            continue
        if not has_required_columns(table.headers):
            continue
        for idx, cells in enumerate(table.rows):
            confidence = confs[idx] if idx < len(confs) else None
            rows.append(normalize_row(list(table.headers), cells, confidence))
    return rows
