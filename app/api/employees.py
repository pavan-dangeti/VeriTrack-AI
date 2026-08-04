from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy import or_, asc, desc

from app.models.user import User
from app.models.employee import Employee

from app.auth.dependencies import get_current_user
from app.db.database import SessionLocal
from app.schemas.employee import (
    EmployeeResponse,
    EmployeeListResponse,
)

router = APIRouter(
    prefix="/employees",
    tags=["Employees"]
)


@router.get(
    "/my",
    response_model=EmployeeListResponse,
)
def my_employees(

    page: int = 1,

    limit: int = 20,

    search: str = "",

    department: str = "",

    sort_by: str = "employee_id",

    sort_order: str = "asc",

    current_user: User = Depends(get_current_user)

):

    db = SessionLocal()

    if current_user.role == "MASTER_ADMIN":

        query = db.query(Employee)

    elif current_user.role == "MANAGER":

        query = db.query(Employee).filter(
            Employee.manager_id == str(current_user.id)
        )

    elif current_user.role == "HR":

        query = db.query(Employee).filter(
            Employee.manager_id == current_user.manager_id
        )

    else:

        db.close()

        raise HTTPException(
            status_code=403,
            detail="Access denied"
        )

    # =====================================
    # Search
    # =====================================

    if search:

        query = query.filter(

            or_(

                Employee.employee_id.ilike(f"%{search}%"),

                Employee.full_name.ilike(f"%{search}%"),

                Employee.company_email.ilike(f"%{search}%"),

                Employee.department.ilike(f"%{search}%")

            )

        )

    # =====================================
    # Department Filter
    # =====================================

    if department:

        query = query.filter(
            Employee.department == department
        )

    # =====================================
    # Sorting
    # =====================================

    sortable_columns = {

        "employee_id": Employee.employee_id,

        "full_name": Employee.full_name,

        "department": Employee.department,

        "created_at": Employee.created_at

    }

    column = sortable_columns.get(
        sort_by,
        Employee.employee_id
    )

    if sort_order.lower() == "desc":

        query = query.order_by(
            desc(column)
        )

    else:

        query = query.order_by(
            asc(column)
        )

    # =====================================
    # Pagination
    # =====================================

    total_records = query.count()

    total_pages = (
        total_records + limit - 1
    ) // limit

    employees = query.offset(

        (page - 1) * limit

    ).limit(

        limit

    ).all()

    db.close()

    return {

        "page": page,

        "limit": limit,

        "total_records": total_records,

        "total_pages": total_pages,

        "employees": [

            {

                "employee_id": employee.employee_id,

                "full_name": employee.full_name,

                "company_email": employee.company_email,

                "personal_email": employee.personal_email,

                "department": employee.department,

                "customer": employee.customer,

                "manager": employee.manager,

                "manager_id": employee.manager_id,

                "created_at": employee.created_at

            }

            for employee in employees

        ]

    }