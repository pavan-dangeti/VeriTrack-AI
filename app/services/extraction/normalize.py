"""Normalization layer: any source -> one internal record format.

Internal record (dict):
    employee_code: str          (raw as-read; validated later by analyze)
    full_name: str
    official_email: str | None
    personal_email: str | None
    department: str | None
    ...any other columns preserved under data["extra"]

Column aliases are matched case/whitespace-insensitively; messy headers like
"  Customer Leave ", "EMP CODE", "Emp Name" all normalize.
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

# GETS leave columns are located separately but normalized into extras.
LEAVE_COLUMN_ALIASES = {
    "customer_leave": ("customer leave",),
    "sacha_leave": ("sacha leave",),
}


@dataclass
class NormalizedRow:
    values: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None  # overall row confidence (OCR path)
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
    """Maps canonical field name -> actual header string found."""
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
    return mapping


def has_required_columns(headers: list[str]) -> bool:
    m = build_header_map(headers)
    return "employee_code" in m and "full_name" in m


def has_leave_columns(headers: list[str]) -> bool:
    m = build_header_map(headers)
    return "customer_leave" in m and "sacha_leave" in m


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
    low_confidence_fields: list[str] = []
    for canonical, header in mapping.items():
        raw_value = cell_by_header.get(_norm_header(header), "")
        text = str(raw_value if raw_value is not None else "").strip()
        if canonical in ("official_email", "personal_email"):
            values[canonical] = normalize_email(text)
        else:
            values[canonical] = text

    # Preserve everything else (leave columns land here too).
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
    if low_confidence_fields:
        row.needs_review = True
    return row


GETS_DAY_RE = re.compile(r"^day\s*(\d{1,2})(?:\s*\(\w{2}\))?\s*$", re.IGNORECASE)


def is_gets_table(headers: list[str]) -> bool:
    """Timesheet layout: a run of day-numbered columns marks a GETS sheet."""
    return sum(1 for h in headers if GETS_DAY_RE.match(str(h or "").strip())) >= 5


def normalize_gets_row(
    headers: list[str],
    raw_cells: list[Any],
    confidence: float | None = None,
) -> NormalizedRow:
    """GETS timesheets have a fixed schema. The 6 cells before the day grid are
    always: person-code cell, name(+STD/NC), project id, project name, task id,
    remarks; after the day columns comes Total. Generic alias matching can't
    express this (the header contains merged multi-row labels), so map
    positionally instead."""
    cells = [str(c if c is not None else "").strip() for c in raw_cells]
    day_idx = [i for i, h in enumerate(headers) if GETS_DAY_RE.match(str(h or "").strip())]
    first_day = day_idx[0] if day_idx else 6

    values: dict[str, Any] = {}
    extras: dict[str, str] = {}

    person = cells[0] if cells else ""
    m = re.match(r"^(\d{3,})", person.replace(" ", ""))
    values["employee_code"] = m.group(1) if m else person.strip()

    name_cell = cells[1] if len(cells) > 1 else ""
    kind = re.search(r"\b(STD|NC)\s*$", name_cell)
    values["full_name"] = name_cell[: kind.start()].rstrip() if kind else name_cell

    extras = {
        "hour_type": kind.group(1) if kind else "",
        "project_id": cells[2] if len(cells) > 2 else "",
        "project_name": cells[3] if len(cells) > 3 else "",
        "task_id": cells[4] if len(cells) > 4 else "",
        "remarks": cells[5] if len(cells) > 5 else "",
    }
    for i in day_idx:
        n = GETS_DAY_RE.match(str(headers[i]).strip()).group(1)
        extras[f"day_{int(n):02d}"] = cells[i] if i < len(cells) else ""
    for i, h in enumerate(headers):
        hs = str(h or "").strip().lower()
        if hs.startswith("tota") and i < len(cells):
            extras["total"] = cells[i]
    extras = {k: v for k, v in extras.items() if v != ""}
    if extras:
        values["extra"] = extras

    row = NormalizedRow(values=values, confidence=confidence)
    code = (values["employee_code"] or "").strip()
    code_ok = bool(re.fullmatch(r"\d{3,}", code))
    name = values["full_name"].lower()
    is_summary = (not code) and ("total" in name or "totals" in name or name == "")
    # A 38-cell timesheet row flagged on min-conf cell is noise; flag only
    # identity-level failure (code unreadable on a real employee row) or deep
    # uncertainty. Sheet-native summary lines (empty code) are structural, not
    # OCR failures, so they never surface in the review queue.
    if is_summary:
        row.needs_review = False
    elif not code_ok:
        row.needs_review = True
        row.review_note = "employee code unreadable"
    elif confidence is not None and confidence < 0.5:
        row.needs_review = True
        row.review_note = f"low OCR confidence ({confidence:.2f})"
    return row


def normalize_tables(tables) -> list[NormalizedRow]:
    rows: list[NormalizedRow] = []
    for table in tables:
        if not table.headers:
            continue
        confs = getattr(table, "row_confidences", None) or []
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
