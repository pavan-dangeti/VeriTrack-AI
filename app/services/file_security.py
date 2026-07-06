import hashlib
import os
import re
from pathlib import Path

from fastapi import HTTPException

from app.db.database import SessionLocal
from app.models.upload_history import UploadHistory

# Maximum upload size (50 MB)
MAX_FILE_SIZE = 50 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".csv",
    ".xlsx",
    ".xls"
}

ALLOWED_CONTENT_TYPES = {
    "text/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
}


def validate_extension(filename: str):

    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:

        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {extension}"
        )


def validate_content_type(content_type: str):

    if content_type not in ALLOWED_CONTENT_TYPES:

        raise HTTPException(
            status_code=400,
            detail="Invalid Content Type"
        )


def validate_file_size(size: int):

    if size > MAX_FILE_SIZE:

        raise HTTPException(
            status_code=400,
            detail="File exceeds 50 MB limit"
        )


def sanitize_filename(filename: str):

    filename = os.path.basename(filename)

    filename = re.sub(
        r"[^A-Za-z0-9._-]",
        "_",
        filename
    )

    return filename


def calculate_sha256(filepath: str):

    sha = hashlib.sha256()

    with open(filepath, "rb") as file:

        while True:

            data = file.read(4096)

            if not data:
                break

            sha.update(data)

    return sha.hexdigest()

def check_duplicate_upload(file_hash: str):

    db = SessionLocal()

    existing = (

        db.query(UploadHistory)

        .filter(
            UploadHistory.file_hash == file_hash
        )

        .first()

    )

    db.close()

    if existing:

        raise HTTPException(

            status_code=409,

            detail="This file has already been uploaded."

        )