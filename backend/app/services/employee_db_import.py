from app.db.database import SessionLocal
from app.models.employee import Employee

from app.services.employee_import_service import (
    read_employee_file
)


def import_employees(
    file_path: str,
    manager_id: str
):

    data = read_employee_file(file_path)

    db = SessionLocal()

    inserted = 0
    skipped = 0

    for row in data["records"]:

        employee_id = str(
            row.get("Employee ID", "")
        )

        existing = db.query(Employee).filter(
            Employee.employee_id == employee_id
        ).first()

        if existing:
            skipped += 1
            continue

        employee = Employee(

            employee_id=employee_id,

            full_name=row.get(
                "Employee Name"
            ),

            department=row.get(
                "Department"
            ),

            manager_id=manager_id

        )

        db.add(employee)

        inserted += 1

    db.commit()
    db.close()

    return {
        "inserted": inserted,
        "skipped": skipped
    }