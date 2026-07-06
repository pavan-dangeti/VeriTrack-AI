from fastapi import APIRouter
from app.services.file_detector import detect_file_type

router = APIRouter(
    prefix="/detection",
    tags=["Detection"]
)


@router.get("/file-type")
def get_file_type(filename: str):

    return detect_file_type(filename)