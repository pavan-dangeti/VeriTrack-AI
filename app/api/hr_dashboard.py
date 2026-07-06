from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from app.auth.dependencies import get_current_user

from app.db.database import SessionLocal

from app.models.user import User
from app.models.employee import Employee
from app.models.upload_history import UploadHistory
from app.models.report_history import ReportHistory

router = APIRouter(
    prefix="/hr-dashboard",
    tags=["HR Dashboard"]
)


@router.get("/")
def hr_dashboard(
    current_user: User = Depends(get_current_user)
):

    if current_user.role != "HR":
        raise HTTPException(
            status_code=403,
            detail="Only HR can access this dashboard"
        )

    db = SessionLocal()

    manager = db.query(User).filter(
        User.id == current_user.manager_id
    ).first()

    if manager is None:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="No manager assigned"
        )

    employee_count = db.query(Employee).filter(
        Employee.manager_id == str(manager.id)
    ).count()

    employee_uploads = db.query(
        UploadHistory
    ).filter(
        UploadHistory.uploaded_by == manager.email,
        UploadHistory.category == "EMPLOYEE_DATA"
    ).count()

    gets_uploads = db.query(
        UploadHistory
    ).filter(
        UploadHistory.uploaded_by == manager.email,
        UploadHistory.category == "GETS_SHEET"
    ).count()

    reports = db.query(
        ReportHistory
    ).filter(
        ReportHistory.downloaded_by == manager.email
    ).order_by(
        ReportHistory.downloaded_at.desc()
    ).limit(10).all()

    db.close()

    return {

        "hr": {
            "name": current_user.name,
            "email": current_user.email
        },

        "manager": {
            "name": manager.name,
            "email": manager.email
        },

        "team": {
            "employees": employee_count
        },

        "uploads": {
            "employee_files": employee_uploads,
            "gets_files": gets_uploads
        },

        "reports": reports

    }