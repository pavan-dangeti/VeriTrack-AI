from fastapi import APIRouter
from app.services.data_extractor import (
    extract_spreadsheet
)

router = APIRouter(
    prefix="/extract",
    tags=["Extraction"]
)


@router.get("/spreadsheet")
def extract_data(file_path: str):

    return extract_spreadsheet(
        file_path
    )