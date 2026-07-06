from app.db.database import SessionLocal

from app.models.employee import Employee
from app.models.upload_history import UploadHistory
from app.models.report_history import ReportHistory
from app.models.audit_log import AuditLog


def get_dashboard_analytics():

    db = SessionLocal()

    total_employees = db.query(Employee).count()

    total_uploads = db.query(
        UploadHistory
    ).count()

    total_reports = db.query(
        ReportHistory
    ).count()

    total_audit_logs = db.query(
        AuditLog
    ).count()

    departments = {}

    employees = db.query(Employee).all()

    for employee in employees:

        department = (
            employee.department
            if employee.department
            else "Unknown"
        )

        departments[department] = (
            departments.get(
                department,
                0
            ) + 1
        )

    department_summary = []

    for dept, count in departments.items():

        department_summary.append({

            "department": dept,

            "employees": count

        })

    department_summary.sort(
        key=lambda x: x["employees"],
        reverse=True
    )

    recent_uploads = db.query(
        UploadHistory
    ).order_by(
        UploadHistory.created_at.desc()
    ).limit(5).all()

    uploads = []

    for upload in recent_uploads:

        uploads.append({

            "filename":
                upload.filename,

            "category":
                upload.category,

            "uploaded_by":
                upload.uploaded_by,

            "uploaded_at":
                upload.created_at

        })

    db.close()

    return {

        "overview": {

            "employees":
                total_employees,

            "uploads":
                total_uploads,

            "reports":
                total_reports,

            "audit_logs":
                total_audit_logs

        },

        "department_summary":
            department_summary,

        "recent_uploads":
            uploads

    }