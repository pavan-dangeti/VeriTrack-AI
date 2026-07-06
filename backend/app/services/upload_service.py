import os

from app.db.database import SessionLocal
from app.models.upload_history import UploadHistory


EMPLOYEE_DIR = "app/uploads/employees"
GETS_DIR = "app/uploads/gets"


def get_latest_employee_file():

    db = SessionLocal()

    upload = (
        db.query(UploadHistory)
        .filter(
            UploadHistory.category == "EMPLOYEE_DATA"
        )
        .order_by(UploadHistory.created_at.desc())
        .first()
    )

    db.close()

    if not upload:
        return None

    return os.path.join(
        EMPLOYEE_DIR,
        upload.filename
    )


def get_latest_gets_file():

    db = SessionLocal()

    upload = (
        db.query(UploadHistory)
        .filter(
            UploadHistory.category == "GETS_SHEET"
        )
        .order_by(UploadHistory.created_at.desc())
        .first()
    )

    db.close()

    if not upload:
        return None

    return os.path.join(
        GETS_DIR,
        upload.filename
    )