from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class EmployeeResponse(BaseModel):
    employee_id: str
    full_name: str
    company_email: str
    personal_email: Optional[str] = None
    department: str
    customer: Optional[str] = None
    manager: Optional[str] = None
    manager_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class EmployeeListResponse(BaseModel):
    page: int
    limit: int
    total_records: int
    total_pages: int
    employees: list[EmployeeResponse]