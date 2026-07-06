from fastapi import APIRouter
from fastapi import UploadFile
from fastapi import File
from fastapi import Depends
from fastapi import BackgroundTasks

from app.models.user import User
from app.auth.permissions import require_permission
from app.core.logger import logger

from app.db.database import SessionLocal
from app.models.upload_history import UploadHistory

from app.services.employee_db_import import import_employees
from app.services.audit_service import log_action
from app.services.background_jobs import process_gets_sheet

from app.services.file_security import (
    validate_extension,
    validate_content_type,
    validate_file_size,
    sanitize_filename,
    calculate_sha256,
    check_duplicate_upload
)

from datetime import datetime
import os

router = APIRouter(
    prefix="/uploads",
    tags=["Uploads"]
)

EMPLOYEE_UPLOAD_DIR = "app/uploads/employees"
GETS_UPLOAD_DIR = "app/uploads/gets"

os.makedirs(EMPLOYEE_UPLOAD_DIR, exist_ok=True)
os.makedirs(GETS_UPLOAD_DIR, exist_ok=True)


# =====================================================
# Upload Employee Master Data
# =====================================================

@router.post("/employee-data")
async def upload_employee_data(
    file: UploadFile = File(...),
    current_user: User = Depends(
        require_permission("can_upload_employee")
    )
):

    validate_extension(file.filename)
    validate_content_type(file.content_type)

    contents = await file.read()

    validate_file_size(len(contents))

    safe_filename = sanitize_filename(file.filename)

    file_path = os.path.join(
        EMPLOYEE_UPLOAD_DIR,
        safe_filename
    )

    with open(file_path, "wb") as buffer:
        buffer.write(contents)

    file_hash = calculate_sha256(file_path)

    check_duplicate_upload(file_hash)

    result = import_employees(
        file_path,
        str(current_user.id)
    )

    db = SessionLocal()

    history = UploadHistory(
        filename=file.filename,
        file_hash=file_hash,
        category="EMPLOYEE_DATA",
        status="UPLOADED",
        uploaded_by=current_user.email
    )

    db.add(history)
    db.commit()

    logger.info(
        f"{current_user.email} uploaded Employee file {file.filename}"
    )

    db.close()

    return {

        "message": "Employee file uploaded successfully",

        "filename": file.filename,

        "uploaded_at": datetime.now(),

        "inserted": result["inserted"],

        "skipped": result["skipped"]

    }


# =====================================================
# Upload Monthly GETS Sheet
# =====================================================

@router.post("/gets-sheet")
async def upload_gets_sheet(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(
        require_permission("can_upload_gets")
    )
):

    start_time = datetime.now()

    validate_extension(file.filename)

    validate_content_type(file.content_type)

    contents = await file.read()

    validate_file_size(len(contents))

    safe_filename = sanitize_filename(file.filename)

    file_path = os.path.join(
        GETS_UPLOAD_DIR,
        safe_filename
    )

    with open(file_path, "wb") as buffer:
        buffer.write(contents)

    file_hash = calculate_sha256(file_path)

    check_duplicate_upload(file_hash)

    db = SessionLocal()

    history = UploadHistory(
        filename=file.filename,
        file_hash=file_hash,
        category="GETS_SHEET",
        status="PROCESSING",
        uploaded_by=current_user.email
    )

    db.add(history)
    db.commit()
    db.close()

    logger.info(
       f"{current_user.email} uploaded GETS file {file.filename}"
    )

    background_tasks.add_task(
        process_gets_sheet,
        str(current_user.id),
        current_user.email,
        current_user.name,
        file_path,
        file.filename
    )

    return {

        "message": "GETS sheet uploaded successfully.",

        "status": "PROCESSING",

        "filename": file.filename,

        "uploaded_by": current_user.email,

        "uploaded_at": start_time,

        "info": "Compliance analysis has started in the background. Check Report History after a few seconds."

    }