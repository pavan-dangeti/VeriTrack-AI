from app.services.leave_comparison_service import compare_leave_data
from app.services.report_generator import generate_compliance_report
from app.services.ai_recommendation_service import generate_ai_summary
from app.services.email_service import send_compliance_report_email
from app.services.audit_service import log_action

from app.db.database import SessionLocal

from app.models.report_history import ReportHistory
from app.models.upload_history import UploadHistory


def process_gets_sheet(
    manager_id: str,
    manager_email: str,
    manager_name: str,
    gets_file: str,
    uploaded_filename: str
):

    # ==========================================
    # Compare Employee vs GETS
    # ==========================================

    comparison = compare_leave_data(
        manager_id=manager_id,
        gets_file=gets_file
    )

    # ==========================================
    # AI Recommendation
    # ==========================================

    ai_summary = generate_ai_summary(
        comparison
    )

    # ==========================================
    # Generate Compliance Report
    # ==========================================

    report = generate_compliance_report(
        manager_name=manager_name,
        comparison=comparison
    )

    db = SessionLocal()

    # ==========================================
    # Save Report History
    # ==========================================

    report_history = ReportHistory(
        manager_id=manager_id,
        manager_email=manager_email,
        filename=report["filename"],
        report_path=report["filepath"]
    )

    db.add(report_history)

    # ==========================================
    # Update Upload History
    # ==========================================

    upload = (
        db.query(UploadHistory)
        .filter(
            UploadHistory.filename == uploaded_filename
        )
        .first()
    )

    if upload:
        upload.status = "COMPLETED"

    db.commit()
    db.close()

    # ==========================================
    # Email Report
    # ==========================================

    send_compliance_report_email(
        receiver=manager_email,
        manager_name=manager_name,
        comparison=comparison,
        report_name=report["filename"]
    )

    # ==========================================
    # Audit Log
    # ==========================================

    log_action(
        manager_email,
        "BACKGROUND_GETS_PROCESS",
        report["filename"]
    )

    print("GETS Background Processing Completed Successfully")