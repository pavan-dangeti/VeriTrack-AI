"""GETS analysis engine.

Sequence (per spec):
  1. verify employee ID format
  2. verify employee exists in THAT manager's repository (cross-reference)
  3. locate Customer Leave / Sacha Leave columns (normalized aliases)
  4. rule: Customer Leave ticked AND Sacha Leave blank -> VIOLATION
  5. dedup per employee per run (DB unique constraint + first-wins insert)
  6. email resolution: Official -> Personal -> none (SKIPPED_NO_EMAIL)

Tick parsing tolerates messy real-world values:
    ticked:   ✓ ✔ ☑ x X y Y yes true 1 [x] done
    unticked/blank: "", "-", "no", "false", "0", "n", whitespace, nan
"""

import re

# --- value parsers -------------------------------------------------------------

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


def evaluate_violation(customer_leave, sacha_leave) -> tuple[bool, str]:
    """Returns (is_violation, reason). The product's core business rule."""
    customer = str(customer_leave or "").strip()
    sacha = str(sacha_leave or "").strip()
    if parse_ticked(customer) and parse_blank(sacha):
        return (
            True,
            f"Customer Leave is ticked ('{customer}') but Sacha Leave is blank"
            + (f" ('{sacha}')" if sacha else ""),
        )
    return False, ""


def resolve_email(*, official: str | None, personal: str | None) -> str | None:
    return official or personal or None


class AnalysisInputError(Exception):
    pass


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

    # 1. employee ID format
    from app.services.employee_service import validate_employee_code

    if not code or not validate_employee_code(code):
        return "BAD_ID_FORMAT", {"employee_code": code[:64]}

    # leave columns present? (normalized as first-class fields)
    customer = row_values.get("customer_leave")
    sacha = row_values.get("sacha_leave")
    if customer is None or sacha is None:
        return "MISSING_COLUMNS", {"employee_code": code}

    # 2. exists in this manager's repository?
    record = repo_lookup.get(code.lower())
    if record is None:
        return (
            "NOT_IN_REPO",
            {
                "employee_code": code,
                "reason": "Employee ID not found in manager's repository",
            },
        )

    # 3./4. violation rule
    violation, reason = evaluate_violation(customer, sacha)
    payload = {
        "employee_code": code,
        "employee_name": record.get("full_name"),
        "customer_leave_value": customer,
        "sacha_leave_value": sacha,
    }
    if violation:
        payload["violation_reason"] = reason
        official = record.get("official_email")
        personal = record.get("personal_email")
        payload["email_to"] = resolve_email(official=official, personal=personal)
        return "MATCHED_VIOLATION", payload
    return "NO_VIOLATION", payload
