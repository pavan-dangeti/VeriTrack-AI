import os

SUPPORTED_TYPES = {
    ".csv": "CSV",
    ".xlsx": "EXCEL",
    ".xls": "EXCEL",
    ".pdf": "PDF",
    ".png": "IMAGE",
    ".jpg": "IMAGE",
    ".jpeg": "IMAGE"
}


def detect_file_type(filename: str):

    extension = os.path.splitext(
        filename
    )[1].lower()

    return {
        "extension": extension,
        "file_type": SUPPORTED_TYPES.get(
            extension,
            "UNKNOWN"
        )
    }