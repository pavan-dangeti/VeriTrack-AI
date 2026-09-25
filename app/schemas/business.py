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
    processed_at: datetime | None = None
    sheet_status: str | None = None
    sheet_period: str | None = None
    sheet_employee: str | None = None


class BatchDetailOut(BatchOut):
    files: list[FileStatusOut]


class EmployeeFieldUpdate(BaseModel):
    model_config = {"str_strip_whitespace": True}
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    official_email: str | None = Field(default=None, max_length=320)
    personal_email: str | None = Field(default=None, max_length=320)
    department: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=400)


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
    company_leave_value: str | None
    violation_reason: str
    email_to: str | None
    email_status: str
    sent_at: datetime | None
    details: dict[str, Any] | None = None


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


class LeaveCreate(BaseModel):
    model_config = {"str_strip_whitespace": True}
    employee_code: str = Field(min_length=3, max_length=32)
    start_date: str = Field(description="YYYY-MM-DD (or any common date format)")
    end_date: str | None = None
    leave_type: str | None = Field(default=None, max_length=60)
