from fastapi import APIRouter
from fastapi import Depends
from fastapi.responses import FileResponse

from app.auth.permissions import require_permission
from app.models.user import User

from app.services.audit_service import log_action
from app.services.report_history_service import save_report_history
from app.services.excel_report_service import create_excel_report

from app.db.database import SessionLocal
from app.models.report_history import ReportHistory
from fastapi import HTTPException
from datetime import datetime

router = APIRouter(
    prefix="/reports",
    tags=["Reports"]
)


@router.get("/compliance-excel")
def download_compliance_excel(
    current_user: User = Depends(
        require_permission("can_download_reports")
    )
):

    file_path = create_excel_report()

    save_report_history(
        filename="Compliance_Report.xlsx",
        downloaded_by=current_user.email
    )

    log_action(
        current_user.email,
        "DOWNLOAD_REPORT",
        "Compliance Report"
    )

    return FileResponse(
        path=file_path,
        filename="Compliance_Report.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@router.get("/history")
def report_history(
    current_user: User = Depends(
        require_permission("can_view_reports")
    )
):

    db = SessionLocal()

    # Managers can only view their own reports
    if current_user.role == "MANAGER":

        reports = (
            db.query(ReportHistory)
            .filter(
                ReportHistory.manager_email == current_user.email
            )
            .order_by(
                ReportHistory.generated_at.desc()
            )
            .all()
        )

    # Admin / HR can view all reports
    else:

        reports = (
            db.query(ReportHistory)
            .order_by(
                ReportHistory.generated_at.desc()
            )
            .all()
        )

    result = []

    for report in reports:

        result.append({

            "id": str(report.id),

            "manager_email": report.manager_email,

            "filename": report.filename,

            "report_type": report.report_type,

            "report_path": report.report_path,

            "generated_at": report.generated_at,

            "downloaded_by": report.downloaded_by,

            "downloaded_at": report.downloaded_at

        })

    db.close()

    return result

@router.get("/download/{report_id}")
def download_report(
    report_id: str,
    current_user: User = Depends(
        require_permission("can_download_reports")
    )
):

    db = SessionLocal()

    report = (
        db.query(ReportHistory)
        .filter(
            ReportHistory.id == report_id
        )
        .first()
    )

    if not report:

        db.close()

        raise HTTPException(
            status_code=404,
            detail="Report not found"
        )

    report.downloaded_by = current_user.email

    report.downloaded_at = datetime.utcnow()

    db.commit()

    log_action(
        current_user.email,
        "DOWNLOAD_REPORT",
        report.filename
    )

    db.close()

    return FileResponse(
        path=report.report_path,
        filename=report.filename,
        media_type="application/octet-stream"
    )