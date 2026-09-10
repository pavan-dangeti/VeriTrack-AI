import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    status: str
    total_files: int
    processed_files: int
    failed_files: int
    created_at: datetime
    completed_at: datetime | None
    # Uploader attribution (name, email) — populated for cross-manager views.
    manager_email: str | None = None
    manager_name: str | None = None


class FileStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    original_filename: str
    content_type_detected: str | None
    file_size: int
    status: str
    error_message: str | None
    rows_extracted: int | None
    needs_review_count: int = 0


class BatchDetailOut(BatchOut):
    files: list[FileStatusOut]


class EmployeeFieldUpdate(BaseModel):
    """Inline correction — edit any subset of editable fields."""

    model_config = {"str_strip_whitespace": True}
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    official_email: str | None = Field(default=None, max_length=320)
    personal_email: str | None = Field(default=None, max_length=320)
    department: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=400)


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_employee(cls, emp) -> dict:
        version = emp.current_version
        return {
            "id": str(emp.id),
            "manager_id": str(emp.manager_id),
            "employee_code": emp.employee_code,
            "full_name": version.full_name if version else "",
            "official_email": version.official_email if version else None,
            "personal_email": version.personal_email if version else None,
            "department": version.department if version else None,
            "updated_at": emp.updated_at.isoformat() if emp.updated_at else None,
        }


class RunTotals(BaseModel):
    files_processed: int
    rows_processed: int
    matched: int
    violations: int
    emails_sent: int
    emails_missing: int
    emails_errored: int
    skipped: int


class ViolationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    employee_code: str
    employee_name: str | None
    customer_leave_value: str | None
    sacha_leave_value: str | None
    violation_reason: str
    email_to: str | None
    email_status: str
    sent_at: datetime | None


class RunDetailOut(BaseModel):
    run_id: str
    batch_id: str
    manager_id: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    totals: RunTotals
    violations: list[ViolationOut]
    skipped_rows: list[dict[str, Any]]


class ExportRequest(BaseModel):
    format: str = Field(pattern="^(csv|xlsx|pdf|png)$")
    columns: list[str] | None = None
