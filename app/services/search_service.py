from sqlalchemy import or_

from app.db.database import SessionLocal

from app.models.employee import Employee
from app.models.user import User
from app.models.upload_history import UploadHistory
from app.models.report_history import ReportHistory


def global_search(query: str):

    db = SessionLocal()

    # ============================
    # Employees
    # ============================

    employees = db.query(Employee).filter(

        or_(

            Employee.employee_id.ilike(f"%{query}%"),

            Employee.full_name.ilike(f"%{query}%"),

            Employee.company_email.ilike(f"%{query}%"),

            Employee.department.ilike(f"%{query}%")

        )

    ).limit(10).all()

    # ============================
    # Users
    # ============================

    users = db.query(User).filter(

        or_(

            User.name.ilike(f"%{query}%"),

            User.email.ilike(f"%{query}%")

        )

    ).limit(10).all()

    # ============================
    # Uploads
    # ============================

    uploads = db.query(
        UploadHistory
    ).filter(

        UploadHistory.filename.ilike(f"%{query}%")

    ).limit(10).all()

    # ============================
    # Reports
    # ============================

    reports = db.query(
        ReportHistory
    ).filter(

        ReportHistory.filename.ilike(f"%{query}%")

    ).limit(10).all()

    db.close()

    return {

        "employees": [

            {

                "employee_id": e.employee_id,

                "name": e.full_name,

                "department": e.department,

                "email": e.company_email

            }

            for e in employees

        ],

        "users": [

            {

                "name": u.name,

                "email": u.email,

                "role": u.role

            }

            for u in users

        ],

        "uploads": [

            {

                "filename": u.filename,

                "category": u.category,

                "uploaded_by": u.uploaded_by

            }

            for u in uploads

        ],

        "reports": [

            {

                "filename": r.filename,

                "generated_by": r.manager_email,

                "generated_at": r.generated_at

            }

            for r in reports

        ]

    }