from collections import Counter

from app.db.database import SessionLocal

from app.models.employee import Employee
from app.models.upload_history import UploadHistory
from app.models.report_history import ReportHistory


def get_analytics():

    db = SessionLocal()

    employees = db.query(Employee).all()

    uploads = db.query(
        UploadHistory
    ).all()

    reports = db.query(
        ReportHistory
    ).all()

    # =====================================
    # Department Distribution
    # =====================================

    department_counter = Counter()

    for employee in employees:

        department = (
            employee.department
            if employee.department
            else "Unknown"
        )

        department_counter[department] += 1

    departments = []

    for dept, count in department_counter.items():

        departments.append({

            "department": dept,

            "employees": count

        })

    departments.sort(
        key=lambda x: x["employees"],
        reverse=True
    )

    # =====================================
    # Upload Distribution
    # =====================================

    employee_uploads = 0

    gets_uploads = 0

    for upload in uploads:

        if upload.category == "EMPLOYEE_DATA":

            employee_uploads += 1

        elif upload.category == "GETS_SHEET":

            gets_uploads += 1

    upload_distribution = {

        "employee_uploads": employee_uploads,

        "gets_uploads": gets_uploads

    }

    # =====================================
    # KPI
    # =====================================

    overview = {

        "employees": len(employees),

        "uploads": len(uploads),

        "reports": len(reports)

    }

    db.close()

    return {

        "overview": overview,

        "departments": departments,

        "upload_distribution": upload_distribution

    }