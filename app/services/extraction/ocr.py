"""OCR engines for scanned uploads (images and image-only PDFs).

OCR_ENGINE: auto (RapidOCR when installed, else files wait in PENDING_OCR for a reprocess), rapid,
or test (JSON fixture engine for CI). GETS screenshots go to gets_grid, everything else to
generic_table.
"""

from __future__ import annotations

import io
from typing import Any, Protocol

import numpy as np

from app.core.config import settings


class OcrUnavailableError(Exception):
    pass


class OcrEngine(Protocol):
    def extract_tables(self, data: bytes, content_type: str) -> list[Any]: ...

    def available(self) -> bool: ...


def rasterize_pdf(data: bytes, dpi: int = 200) -> list:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(io.BytesIO(data))
    try:
        return [page.render(scale=dpi / 72).to_pil() for page in pdf]
    finally:
        pdf.close()


def load_pages(data: bytes, content_type: str) -> list[np.ndarray]:
    """Image/PDF bytes → list of RGB arrays (EXIF orientation honoured)."""
    from PIL import Image, ImageOps

    if content_type == "application/pdf":
        images = rasterize_pdf(data)
    else:
        img = Image.open(io.BytesIO(data))
        images = [ImageOps.exif_transpose(img)]
    return [np.asarray(im.convert("RGB")) for im in images]


def gets_table(sheet) -> Any:
    from app.services.extraction.readers import RawTable

    days = max(31, sheet.days_in_month)
    headers = ["employee_code", "full_name", "supplier", "job_family", "hour_type",
               "project_id", "project_name", "task_id", "remarks",
               *[f"Day {d}" for d in range(1, days + 1)], "Total"]
    rows, confs = [], []
    for line in sheet.lines:
        hours = line.hours_by_day
        rows.append([
            line.person_id, sheet.employee_name, line.supplier, line.job_family, line.uom,
            line.project_id, line.sub_project, line.sub_project_id, line.remarks,
            *[_fmt(hours.get(d)) for d in range(1, days + 1)],
            _fmt(line.printed_total if line.printed_total is not None else line.computed_total),
        ])
        confs.append(line.confidence)
    return RawTable(headers=headers, rows=rows, row_confidences=confs,
                    meta={"gets_sheet": sheet.to_dict()})


def _fmt(v) -> str:
    if v is None:
        return ""
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


class RapidOcrEngine:
    def available(self) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError:
            return False
        return True

    def extract_tables(self, data: bytes, content_type: str) -> list:
        if not self.available():
            raise OcrUnavailableError(
                "RapidOCR is not installed. pip install rapidocr-onnxruntime"
            )
        from app.services.extraction.generic_table import read_generic_table
        from app.services.extraction.gets_grid import (
            ENGINE_POOL,
            GetsLayoutError,
            _Ocr,
            is_gets_screenshot,
            read_gets_sheet,
        )

        tables = []
        for page in load_pages(data, content_type):
            if is_gets_screenshot(page):
                try:
                    tables.append(gets_table(read_gets_sheet(page)))
                    continue
                except GetsLayoutError:
                    pass  # fall through to the generic reader
            engine = ENGINE_POOL.acquire()
            try:
                tables.append(read_generic_table(page, _Ocr(engine)))
            finally:
                ENGINE_POOL.release(engine)
        return tables


class TestOcrEngine:
    def available(self) -> bool:
        return True

    def extract_tables(self, data: bytes, content_type: str) -> list:
        import json

        from app.services.extraction.readers import RawTable

        try:
            payload = json.loads(data.decode("utf-8"))
            tables = payload["tables"]
        except Exception as exc:
            raise OcrUnavailableError(
                "TestOcrEngine expects a JSON payload: {'tables': [{headers, rows}]}"
            ) from exc
        return [RawTable(headers=t.get("headers", []), rows=t.get("rows", [])) for t in tables]


class UnavailableEngine:
    def available(self) -> bool:
        return False

    def extract_tables(self, data: bytes, content_type: str) -> list:
        raise OcrUnavailableError("No OCR engine configured (set OCR_ENGINE=auto|rapid|test)")


_engine: OcrEngine | None = None


def get_ocr_engine() -> OcrEngine:
    global _engine
    if _engine is None:
        choice = settings.ocr_engine
        if choice == "test":
            _engine = TestOcrEngine()
        else:
            rapid = RapidOcrEngine()
            _engine = rapid if rapid.available() else UnavailableEngine()
    return _engine


def reset_ocr_engine_for_tests() -> None:
    global _engine
    _engine = None
