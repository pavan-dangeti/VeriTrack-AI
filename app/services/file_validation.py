"""Content inspection by magic bytes — never trust the client's filename.

Supported: PDF, xlsx/xlsm (ZIP container + OOXML marker), xls (OLE2),
CSV (text heuristics), PNG, JPEG.
"""

import io
import zipfile

MAGIC_PDF = b"%PDF-"
MAGIC_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .xls
MAGIC_PNG = b"\x89PNG\r\n\x1a\n"
MAGIC_JPEG = b"\xff\xd8\xff"
# entry prefix inside an xlsx zip container
XLSX_ZIP_ENTRY_PREFIX = "xl/"


class FileValidationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def sniff_content_type(data: bytes, declared_filename: str) -> str:
    """Returns canonical internal content type or raises FileValidationError.

    The declared filename/extension is only a tiebreaker for text formats
    (csv); binary formats are identified purely by magic bytes. A mismatch
    between claimed extension and actual bytes is rejected outright.
    """
    if len(data) < 8:
        raise FileValidationError("file_too_small", "File is empty or truncated")

    if data.startswith(MAGIC_PDF):
        _require_extension(declared_filename, {".pdf"}, "PDF")
        return "application/pdf"

    if data.startswith(MAGIC_JPEG):
        _require_extension(declared_filename, {".jpg", ".jpeg"}, "JPEG")
        return "image/jpeg"

    if data.startswith(MAGIC_PNG):
        _require_extension(declared_filename, {".png"}, "PNG")
        return "image/png"

    if data.startswith(MAGIC_OLE2):
        _require_extension(declared_filename, {".xls"}, "XLS")
        return "application/vnd.ms-excel"

    if data.startswith(b"PK\x03\x04"):
        # ZIP container: accept only genuine xlsx (OOXML with xl/ entries),
        # never arbitrary zips disguised with .xlsx names.
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
        except zipfile.BadZipFile as exc:
            raise FileValidationError("corrupt_archive", "Corrupt XLSX container") from exc
        if any(n.startswith(XLSX_ZIP_ENTRY_PREFIX) for n in names) and any(
            n == "[Content_Types].xml" for n in names
        ):
            _require_extension(declared_filename, {".xlsx", ".xlsm"}, "XLSX")
            return (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        raise FileValidationError(
            "zip_disguised", "Archive contents do not match the claimed spreadsheet type"
        )

    # Text heuristic path: CSV only.
    ext = declared_filename.lower().rsplit(".", 1)[-1] if "." in declared_filename else ""
    if ext == "csv" and _looks_like_text(data):
        return "text/csv"
    if _looks_like_text(data):
        raise FileValidationError(
            "type_mismatch",
            f"Plain-text content does not match its extension '.{ext}' — rename to .csv "
            "if this is CSV data",
        )

    raise FileValidationError(
        "unsupported_type", "Unsupported file type (magic-byte inspection failed)"
    )


def _require_extension(filename: str, allowed: set[str], label: str) -> None:
    dot = filename.lower().rfind(".")
    ext = filename[dot:] if dot != -1 else ""
    if ext not in allowed:
        raise FileValidationError(
            "extension_mismatch",
            f"{label} content requires one of {sorted(allowed)} extensions",
        )


def _looks_like_text(data: bytes, sample_limit: int = 4096) -> bool:
    sample = data[:sample_limit]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        try:
            sample.decode("latin-1")
        except UnicodeDecodeError:
            return False
    printable_ratio = sum(c >= 32 or c in (9, 10, 13) for c in sample) / max(len(sample), 1)
    return printable_ratio > 0.95
