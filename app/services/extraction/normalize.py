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


def normalize_tables(tables) -> list[NormalizedRow]:
    rows: list[NormalizedRow] = []
    for table in tables:
        if not table.headers or not has_required_columns(table.headers):
            continue
        confs = getattr(table, "row_confidences", None) or []
        for idx, cells in enumerate(table.rows):
            confidence = confs[idx] if idx < len(confs) else None
            rows.append(normalize_row(list(table.headers), cells, confidence))
    return rows
