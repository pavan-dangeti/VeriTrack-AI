"""Readers turn file bytes into a common RawTable shape."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawTable:
    headers: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    # Optional per-row confidence (OCR paths); feeds the review pipeline.
    row_confidences: list[float | None] | None = None


class ExtractionError(Exception):
    pass


def read_csv(data: bytes) -> list[RawTable]:
    import csv
    import io

    tables: list[RawTable] = []
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ExtractionError("undecodable CSV")

    sample = text[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader if any((cell or "").strip() for cell in row)]
    if not rows:
        return []
    tables.append(RawTable(headers=[(h or "").strip() for h in rows[0]], rows=rows[1:]))
    return tables


def read_xlsx(data: bytes) -> list[RawTable]:
    import io as _io

    from openpyxl import load_workbook

    try:
        wb = load_workbook(_io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise ExtractionError(f"unreadable workbook: {exc}") from exc

    tables: list[RawTable] = []
    for ws in wb.worksheets:
        rows_iter = ws.iter_rows(values_only=True)
        header_row: list | None = None
        body: list[list] = []
        for row in rows_iter:
            cells = ["" if c is None else str(c) for c in row]
            if not any(c.strip() for c in cells):
                continue
            if header_row is None:
                # Header = first non-empty row containing at least 2 labels.
                labels = [c.strip() for c in cells]
                if sum(1 for c in labels if c) >= 2:
                    header_row = labels
                    continue
            body.append(cells)
        if header_row is not None:
            width = len(header_row)
            padded = [(r + [""] * width)[:width] for r in body]
            tables.append(RawTable(headers=header_row, rows=padded))
    wb.close()
    return tables


def read_xls(data: bytes) -> list[RawTable]:

    import xlrd

    try:
        book = xlrd.open_workbook(file_contents=data)
    except Exception as exc:
        raise ExtractionError(f"unreadable legacy workbook: {exc}") from exc

    tables: list[RawTable] = []
    for sheet in book.sheets():
        if sheet.nrows == 0:
            continue
        header = [str(sheet.cell_value(0, c)).strip() for c in range(sheet.ncols)]
        body = [
            [str(sheet.cell_value(r, c)) for c in range(sheet.ncols)]
            for r in range(1, sheet.nrows)
        ]
        tables.append(RawTable(headers=header, rows=body))
    return tables


def read_pdf_text_layer(data: bytes) -> list[RawTable]:
    """Text-layer PDFs (not scans): pypdf line extraction, no model needed."""
    import io as _io

    from pypdf import PdfReader

    try:
        reader = PdfReader(_io.BytesIO(data))
    except Exception as exc:
        raise ExtractionError(f"unreadable PDF: {exc}") from exc

    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        lines.extend(ln.strip() for ln in text.splitlines() if ln.strip())

    if not lines:
        raise ExtractionError(
            "pdf_no_text_layer",
            "PDF has no extractable text layer — it is likely a scan requiring OCR",
        )
    tables = _lines_to_table(lines)
    return [tables] if tables.rows else []


def _lines_to_table(lines: list[str]) -> RawTable:
    """Heuristic: header is the first line with >=2 cells; delimiter sniffed."""
    delims = ["\t", "|", ";", ","]
    best, best_count = ",", -1
    for d in delims:
        counts = [ln.count(d) for ln in lines[:20]]
        avg = sum(counts) / max(len(counts), 1)
        if avg > best_count:
            best, best_count = d, avg
    if best_count <= 0:
        return RawTable()

    def split(line: str) -> list[str]:
        return [c.strip() for c in line.split(best)]

    header = split(lines[0])
    body = [split(ln) for ln in lines[1:]]
    width = len(header)
    body = [(r + [""] * width)[:width] for r in body]
    return RawTable(headers=[h or f"col_{i}" for i, h in enumerate(header)], rows=body)


def read_image_via_ocr(data: bytes, content_type: str) -> list[RawTable]:
    """Scans/images go through the pluggable OCR engine (see ocr.py)."""
    from app.services.extraction.ocr import get_ocr_engine

    engine = get_ocr_engine()
    return engine.extract_tables(data, content_type)


READERS = {
    "text/csv": read_csv,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": read_xlsx,
    "application/vnd.ms-excel": read_xls,
    "application/pdf": lambda data: read_pdf_or_ocr(data),
}


def read_pdf_or_ocr(data: bytes) -> list[RawTable]:
    try:
        return read_pdf_text_layer(data)
    except ExtractionError as exc:
        if "pdf_no_text_layer" in str(exc):
            return read_image_via_ocr(data, "application/pdf")
        raise


def read_any(content_type: str, data: bytes) -> list[RawTable]:
    reader = READERS.get(content_type)
    if reader is None:
        if content_type in ("image/png", "image/jpeg"):
            return read_image_via_ocr(data, content_type)
        raise ExtractionError(f"no reader for {content_type}")
    return reader(data)
