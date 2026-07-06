from fastapi import APIRouter
from fastapi import Depends

from app.auth.permissions import require_permission

from app.models.user import User
from app.models.upload_history import UploadHistory
from app.models.user_request import UserRequest
from app.models.employee import Employee
from app.models.report_history import ReportHistory

from app.db.database import SessionLocal

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"]
)


@router.get("/master")
def master_dashboard(

    current_user: User = Depends(
        require_permission("can_manage_users")
    )

):

    db = SessionLocal()

    # ==========================================
    # Users
    # ==========================================

    total_users = db.query(User).count()

    total_managers = db.query(User).filter(
        User.role == "MANAGER"
    ).count()

    total_hr = db.query(User).filter(
        User.role == "HR_ADMIN"
    ).count()

    # ==========================================
    # Employee Analytics
    # ==========================================

    total_employees = db.query(
        Employee
    ).count()

    # ==========================================
    # Requests
    # ==========================================

    pending_requests = db.query(
        UserRequest
    ).filter(
        UserRequest.status == "PENDING"
    ).count()

    approved_requests = db.query(
        UserRequest
    ).filter(
        UserRequest.status == "APPROVED"
    ).count()

    # ==========================================
    # Uploads
    # ==========================================

    total_uploads = db.query(
        UploadHistory
    ).count()

    employee_uploads = db.query(
        UploadHistory
    ).filter(
        UploadHistory.category == "EMPLOYEE_DATA"
    ).count()

    gets_uploads = db.query(
        UploadHistory
    ).filter(
        UploadHistory.category == "GETS_SHEET"
    ).count()

    # ==========================================
    # Reports
    # ==========================================

    total_reports = db.query(
        ReportHistory
    ).count()

    # ==========================================
    # Department Analytics
    # ==========================================

    departments = {}

    employees = db.query(
        Employee
    ).all()

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

    # ==========================================
    # Recent Uploads
    # ==========================================

    recent_uploads = db.query(
        UploadHistory
    ).order_by(
        UploadHistory.created_at.desc()
    ).limit(5).all()

    upload_history = []

    for upload in recent_uploads:

        upload_history.append({

            "filename": upload.filename,

            "category": upload.category,

            "uploaded_by": upload.uploaded_by,

            "uploaded_at": upload.created_at

        })

    db.close()

    return {

        "overview": {

            "users": total_users,

            "employees": total_employees,

            "reports": total_reports,

            "uploads": total_uploads

        },

        "users": {

            "total": total_users,

            "managers": total_managers,

            "hr_admins": total_hr

        },

        "requests": {

            "pending": pending_requests,

            "approved": approved_requests

        },

        "uploads": {

            "total": total_uploads,

            "employee": employee_uploads,

            "gets": gets_uploads

        },

        "departments":
            department_summary,

        "recent_uploads":
            upload_history

    }