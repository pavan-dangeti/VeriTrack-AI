from app.db.database import SessionLocal
from app.models.report_history import ReportHistory


def save_report_history(
    filename: str,
    downloaded_by: str
):

    db = SessionLocal()

    history = ReportHistory(
        filename=filename,
        downloaded_by=downloaded_by
    )

    db.add(history)
    db.commit()
    db.close()