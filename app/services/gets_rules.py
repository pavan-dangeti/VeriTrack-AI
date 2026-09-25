"""GETS analysis rules.

Tick sheets: Customer Leave ticked and Company Leave blank is a violation. Timesheet screenshots have
no tick-boxes; leave is booked as 'Out Of Office' hours, and each such day must also be in the company
leave register.
"""

import re

TICKED = re.compile(r"^\s*(\[?x\]?|✓|✔|☑|√|y|yes|true|1|done)\s*$", re.IGNORECASE)


def parse_ticked(value) -> bool:
    if value is None:
        return False
    return bool(TICKED.match(str(value)))


def parse_blank(value) -> bool:
    """Blank means 'not ticked' — empty, dash, no/false/0/n, whitespace."""
    if value is None:
        return True
    text = str(value).strip()
    if text == "":
        return True
    if TICKED.match(text):
        return False
    return bool(re.match(r"^(-+|--|n|no|false|0|nan|none)?$", text, re.IGNORECASE))


def evaluate_violation(customer_leave, company_leave) -> tuple[bool, str]:
    """Returns (is_violation, reason)."""
    customer = str(customer_leave or "").strip()
    company = str(company_leave or "").strip()
    if parse_ticked(customer) and parse_blank(company):
        return (
            True,
            f"Customer Leave is ticked ('{customer}') but Company Leave is blank"
            + (f" ('{company}')" if company else ""),
        )
    return False, ""


def resolve_email(*, official: str | None, personal: str | None) -> str | None:
    return official or personal or None


def check_row(
    *,
    row_values: dict,
    repo_lookup: dict[str, dict],  # employee_code -> current version fields
) -> tuple[str, dict]:
    """Classifies one normalized GETS row.

    Returns (status, payload) where status in:
        MATCHED_VIOLATION | NO_VIOLATION | BAD_ID_FORMAT | NOT_IN_REPO | MISSING_COLUMNS
    """

    code = str(row_values.get("employee_code") or "").strip()

    from app.services.employee_service import validate_employee_code

    if not code or not validate_employee_code(code):
        return "BAD_ID_FORMAT", {"employee_code": code[:64]}

    customer = row_values.get("customer_leave")
    company = row_values.get("company_leave")
    if customer is None or company is None:
        return "MISSING_COLUMNS", {"employee_code": code}

    record = repo_lookup.get(code.lower())
    if record is None:
        return (
            "NOT_IN_REPO",
            {
                "employee_code": code,
                "reason": "Employee ID not found in manager's repository",
            },
        )

    violation, reason = evaluate_violation(customer, company)
    payload = {
        "employee_code": code,
        "employee_name": record.get("full_name"),
        "customer_leave_value": customer,
        "company_leave_value": company,
    }
    if violation:
        payload["violation_reason"] = reason
        official = record.get("official_email")
        personal = record.get("personal_email")
        payload["email_to"] = resolve_email(official=official, personal=personal)
        return "MATCHED_VIOLATION", payload
    return "NO_VIOLATION", payload


def is_timesheet_row(values: dict) -> bool:
    extra = values.get("extra") or {}
    return "hour_type" in extra or any(k.startswith("day_") for k in extra)


def customer_leave_dates(values: dict) -> list:
    """Dates of 'Out Of Office' hours on one timesheet row."""
    from datetime import date

    extra = values.get("extra") or {}
    if not extra.get("is_out_of_office"):
        return []
    period = str(extra.get("period") or "")
    m = re.fullmatch(r"(\d{4})-(\d{2})", period)
    if not m:
        return []
    year, month = int(m.group(1)), int(m.group(2))
    out = []
    for day in extra.get("leave_days") or []:
        try:
            out.append(date(year, month, int(day)))
        except (TypeError, ValueError):
            continue
    return out


def evaluate_timesheet_leave(customer: set, register: set) -> tuple[bool, str, list]:
    """(is_violation, reason, missing_dates)."""
    missing = sorted(customer - register)
    if not missing:
        return False, "", []
    shown = ", ".join(d.strftime("%d %b %Y") for d in missing[:10])
    more = f" (+{len(missing) - 10} more)" if len(missing) > 10 else ""
    return (
        True,
        f"Out Of Office on {shown}{more} in GETS (customer leave) has no matching "
        f"company leave entry",
        missing,
    )
