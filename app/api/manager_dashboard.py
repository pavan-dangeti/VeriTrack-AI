from fastapi import APIRouter
from fastapi import Depends

from app.models.user import User
from app.models.employee import Employee
from app.models.upload_history import UploadHistory
from app.models.audit_log import AuditLog
from app.models.report_history import ReportHistory

from app.auth.dependencies import get_current_user
from app.db.database import SessionLocal

router = APIRouter(
    prefix="/manager-dashboard",
    tags=["Manager Dashboard"]
)


@router.get("/")
def manager_dashboard(
    current_user: User = Depends(
        get_current_user
    )
):

    if current_user.role != "MANAGER":
        return {
            "message": "Access denied"
        }

    db = SessionLocal()

    # HRs under this manager
    hr_count = db.query(User).filter(
        User.role == "HR",
        User.manager_id == str(current_user.id)
    ).count()

    # Employees under this manager
    employee_count = db.query(Employee).filter(
        Employee.manager_id == str(current_user.id)
    ).count()

    # Upload statistics
    employee_uploads = db.query(
        UploadHistory
    ).filter(
        UploadHistory.uploaded_by == current_user.email,
        UploadHistory.category == "EMPLOYEE_DATA"
    ).count()

    gets_uploads = db.query(
        UploadHistory
    ).filter(
        UploadHistory.uploaded_by == current_user.email,
        UploadHistory.category == "GETS_SHEET"
    ).count()

    total_uploads = db.query(
        UploadHistory
    ).filter(
        UploadHistory.uploaded_by == current_user.email
    ).count()

    # Recent uploads
    recent_uploads = db.query(
        UploadHistory
    ).filter(
        UploadHistory.uploaded_by == current_user.email
    ).order_by(
        UploadHistory.created_at.desc()
    ).limit(10).all()

    # Comparison statistics
    comparison_count = db.query(
        AuditLog
    ).filter(
        AuditLog.user_email == current_user.email,
        AuditLog.action == "RUN_COMPARISON"
    ).count()

    # Report statistics
    report_count = db.query(
        ReportHistory
    ).filter(
        ReportHistory.downloaded_by == current_user.email
    ).count()

    latest_report = db.query(
        ReportHistory
    ).filter(
        ReportHistory.downloaded_by == current_user.email
    ).order_by(
        ReportHistory.downloaded_at.desc()
    ).first()

    db.close()

    return {

        "manager": {
            "name": current_user.name,
            "email": current_user.email
        },

        "team": {
            "hrs": hr_count,
            "employees": employee_count
        },

        "uploads": {
            "total": total_uploads,
            "employee_files": employee_uploads,
            "gets_files": gets_uploads
        },

        "comparisons": comparison_count,

        "reports": {
            "generated": report_count,
            "latest_report": (
                latest_report.filename
                if latest_report
                else None
            )
        },

        "recent_activity": recent_uploads

    }