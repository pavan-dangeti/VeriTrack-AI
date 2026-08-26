"""Pluggable OCR engines.

Selection (settings.ocr_engine):
  auto  — RapidOCR if installed, else engines degrade gracefully
          (uploads land in PENDING_OCR, retryable via the reprocess API)
  rapid — RapidOCR (PaddleOCR models in ONNX; CPU; works on py3.14/macOS/Linux)
  paddle— full PaddleOCR pipeline for linux workers (see Dockerfile.ocr)
  test  — deterministic fixture engine for CI

Scanned PDFs are rasterized with pypdfium2 before recognition.
"""

from typing import Any, Protocol

from app.core.config import settings


class OcrEngine(Protocol):
    def extract_tables(self, data: bytes, content_type: str) -> list[Any]:
        """Returns RawTable-compatible objects."""
        ...

    def available(self) -> bool: ...


class OcrUnavailableError(Exception):
    pass


# --- shared post-OCR table reconstruction --------------------------------------


def reconstruct_table(lines: list[tuple[list[list[float]], str, float]]) -> list:
    """Rebuilds a logical table from word-level OCR boxes.

    Handles the two classic OCR-table problems:
    1. Scale-safe row banding (dynamic threshold from median glyph height)
    2. Multi-word headers: known column aliases ("employee id", "sacha leave")
       are matched as phrases across adjacent header words; data cells are
       assigned to logical columns by x-center, then merged.
    """
    from app.services.extraction.normalize import FIELD_ALIASES, LEAVE_COLUMN_ALIASES
    from app.services.extraction.readers import RawTable

    if not lines:
        return [RawTable(headers=[], rows=[])]

    items = []
    for box, text, conf in lines:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        items.append({
            "x0": min(xs), "x1": max(xs),
            "yc": sum(ys) / len(ys),
            "h": max(ys) - min(ys),
            "text": str(text).strip(), "conf": float(conf),
        })
    items.sort(key=lambda r: r["yc"])

    heights = sorted(r["h"] for r in items)
    med_h = heights[len(heights) // 2] or 20.0
    bands: list[list[dict]] = []
    current = [items[0]]
    for r in items[1:]:
        if r["yc"] - max(x["yc"] for x in current) <= max(10.0, 0.6 * med_h):
            current.append(r)
        else:
            bands.append(current)
            current = [r]
    bands.append(current)
    for band in bands:
        band.sort(key=lambda r: r["x0"])

    header = bands[0]
    tokens = [c["text"].lower() for c in header]

    phrases = sorted(
        {a.lower() for m in (FIELD_ALIASES, LEAVE_COLUMN_ALIASES)
         for alts in m.values() for a in alts},
        key=len, reverse=True,
    )

    cols: list[dict] = []
    i = 0
    while i < len(tokens):
        hit = _match_phrase_at(tokens, i, [p for p in phrases if len(p.split()) > 1])
        if hit:
            label, n = hit
            cols.append({"label": label, "idx": list(range(i, i + n))})
            i += n
        else:
            cols.append({"label": tokens[i], "idx": [i]})
            i += 1

    def col_span(ci: int) -> tuple[float, float]:
        idxs = cols[ci]["idx"]
        return header[idxs[0]]["x0"], header[idxs[-1]]["x1"]

    boundaries = [
        (col_span(ci)[1] + col_span(ci + 1)[0]) / 2 for ci in range(len(cols) - 1)
    ]

    def assign(x_center: float) -> int:
        for bi, b in enumerate(boundaries):
            if x_center < b:
                return bi
        return len(cols) - 1

    rows_out: list[list[str]] = []
    confidences: list[float | None] = []
    for band in bands[1:]:
        cells: list[str | None] = [None] * len(cols)
        cell_confs: dict[int, float] = {}
        for c in band:
            ci = assign((c["x0"] + c["x1"]) / 2)
            cells[ci] = f"{cells[ci]} {c['text']}".strip() if cells[ci] else c["text"]
            cell_confs[ci] = min(cell_confs.get(ci, 1.0), c["conf"])
        rows_out.append([(c or "") for c in cells])
        confidences.append(min(cell_confs.values()) if cell_confs else None)

    table = RawTable(headers=[c["label"] for c in cols], rows=rows_out)
    table.row_confidences = confidences
    band_texts = [" ".join(c["text"] for c in band) for band in bands]
    return [table], band_texts


def _match_phrase_at(tokens: list[str], start: int, phrases: list[str]) -> tuple[str, int] | None:
    """Fuzzy-matches a known column phrase across 1-3 adjacent OCR header tokens.

    Tolerates the two things OCR does to headers: dropping spaces
    ('EmployeeID') and small misreads ('FulName'). Longest phrases first.
    """
    from difflib import SequenceMatcher

    best: tuple[str, int, float] | None = None
    for phrase in phrases:  # caller supplies longest-first ordering
        target = "".join(phrase.split())
        for n in (1, 2, 3):
            if start + n > len(tokens):
                break
            candidate = "".join(t.replace(" ", "") for t in tokens[start:start + n])
            if abs(len(candidate) - len(target)) > 3:
                continue
            ratio = SequenceMatcher(None, candidate, target).ratio()
            if ratio >= 0.78 and (best is None or ratio > best[2]):
                best = (phrase, n, ratio)
    return (best[0], best[1]) if best else None



_EMAIL_RE = None


def _with_line_fallback(bundle):
    """When the detector merges whole lines into few boxes, tabular
    reconstruction starves (<2 populated cells). High-signal fields
    (emails, employee codes, names) are recoverable by pattern parsing."""
    import re

    global _EMAIL_RE
    if _EMAIL_RE is None:
        _EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

    from app.services.employee_service import validate_employee_code
    from app.services.extraction.normalize import has_required_columns
    from app.services.extraction.readers import RawTable

    tables, band_texts = bundle
    table = tables[0] if tables else None
    if table is None:
        return tables

    def populated(row):
        return sum(1 for c in row if (c or "").strip())

    headers_ok = has_required_columns(table.headers)
    starved_rows = any(populated(r) < 2 for r in table.rows)
    if headers_ok and not starved_rows:
        return tables

    # Canonical rebuild from raw band texts (header band skipped).
    rebuilt = RawTable(
        headers=["employee_code", "full_name", "official_email", "personal_email"],
        rows=[],
        row_confidences=[],
    )
    confs = table.row_confidences or []
    for bi, band_text in enumerate(band_texts[1:]):
        emails = list(dict.fromkeys(_EMAIL_RE.findall(band_text)))
        tokens = _EMAIL_RE.sub(" ", band_text).split()
        code = next((t for t in tokens if validate_employee_code(t)), "")
        name_tokens = [t for t in tokens if t != code and len(t) > 1]
        name = " ".join(name_tokens[:3])
        rebuilt.rows.append([
            code, name,
            emails[0] if emails else "",
            emails[1] if len(emails) > 1 else "",
        ])
        rebuilt.row_confidences.append(confs[bi] if bi < len(confs) else None)
    return [rebuilt]

    return [rebuilt]


def rasterize_pdf(data: bytes, dpi: int = 200) -> list:
    import io as _io  # noqa: PLC0415

    import pypdfium2 as pdfium  # noqa: PLC0415

    pdf = pdfium.PdfDocument(_io.BytesIO(data))
    images = []
    for page in pdf:
        bitmap = page.render(scale=dpi / 72)
        images.append(bitmap.to_pil())
    return images


class RapidOcrEngine:
    """RapidOCR: PaddleOCR det/rec models served through onnxruntime.

    Runs on CPython 3.14 / macOS ARM / Linux — no Python version pinning.
    Row confidence comes from per-cell scores and feeds the review pipeline.
    """

    _instance = None

    def available(self) -> bool:
        try:
            self._get_engine()
            return True
        except OcrUnavailableError:
            return False

    @classmethod
    def _get_engine(cls):
        if cls._instance is None:
            try:
                from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415
            except ImportError as exc:
                raise OcrUnavailableError(
                    "RapidOCR is not installed. pip install rapidocr-onnxruntime "
                    "(or set OCR_ENGINE=paddle on a linux worker with Dockerfile.ocr)."
                ) from exc
            cls._instance = RapidOCR()
        return cls._instance

    def extract_tables(self, data: bytes, content_type: str) -> list:
        engine = self._get_engine()

        if content_type == "application/pdf":
            pages = rasterize_pdf(data)
        else:
            import io as _io  # noqa: PLC0415

            from PIL import Image  # noqa: PLC0415

            pages = [Image.open(_io.BytesIO(data)).convert("RGB")]

        import numpy as np  # noqa: PLC0415

        all_lines: list[tuple[list[list[float]], str, float]] = []
        for image in pages:
            result, _elapsed = engine(np.asarray(image))
            for box, text, conf in result or []:
                all_lines.append((box, str(text), float(conf)))
        table_bundle = reconstruct_table(all_lines)
        return _with_line_fallback(table_bundle)

    @staticmethod
    def row_confidence(lines) -> float | None:
        confs = [c for _, _, c in lines]
        return min(confs) if confs else None


class PaddleOcrEngine:
    """Full PaddleOCR pipeline for production linux workers."""

    def available(self) -> bool:
        try:
            import paddleocr  # noqa: F401, PLC0415
            return True
        except ImportError:
            return False

    def extract_tables(self, data: bytes, content_type: str) -> list:
        try:
            from paddleocr import PaddleOCR  # noqa: PLC0415
        except ImportError as exc:
            raise OcrUnavailableError(
                "paddlepaddle/paddleocr have no wheels for this platform/python. "
                "Run the provided Dockerfile.ocr sidecar (python:3.12) or use "
                "OCR_ENGINE=rapid."
            ) from exc
        ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        lines: list[tuple[list[list[float]], str, float]] = []
        if content_type == "application/pdf":
            pages = rasterize_pdf(data)
        else:
            import io as _io  # noqa: PLC0415

            from PIL import Image  # noqa: PLC0415

            pages = [Image.open(_io.BytesIO(data)).convert("RGB")]
        for image in pages:
            raw = ocr.ocr(image, cls=True)
            for page in raw or []:
                for box, (text, conf) in page or []:
                    lines.append((box, str(text), float(conf)))
        table_bundle = reconstruct_table(lines)
        return _with_line_fallback(table_bundle)


class TestOcrEngine:
    """Deterministic fixture engine for tests/demo (JSON payload input)."""

    def available(self) -> bool:
        return True

    def extract_tables(self, data: bytes, content_type: str) -> list:
        import json  # noqa: PLC0415

        from app.services.extraction.readers import RawTable  # noqa: PLC0415

        try:
            payload = json.loads(data.decode("utf-8"))
            tables = payload["tables"]
        except Exception as exc:
            raise OcrUnavailableError(
                "TestOcrEngine expects a JSON payload: {'tables': [{headers, rows}]}"
            ) from exc
        return [
            RawTable(headers=t.get("headers", []), rows=t.get("rows", [])) for t in tables
        ]


class UnavailableEngine:
    """Explicit placeholder used when OCR_ENGINE points at nothing usable."""

    def available(self) -> bool:
        return False

    def extract_tables(self, data: bytes, content_type: str) -> list:
        raise OcrUnavailableError(
            "No OCR engine configured (set OCR_ENGINE=auto|rapid|paddle|test)"
        )


_engine: OcrEngine | None = None


def get_ocr_engine() -> OcrEngine:
    global _engine
    if _engine is None:
        choice = settings.ocr_engine
        if choice == "test":
            _engine = TestOcrEngine()
        elif choice == "rapid":
            _engine = RapidOcrEngine()
        elif choice == "paddle":
            _engine = PaddleOcrEngine()
        else:  # auto
            rapid = RapidOcrEngine()
            _engine = rapid if rapid.available() else UnavailableEngine()
    return _engine


def reset_ocr_engine_for_tests() -> None:
    global _engine
    _engine = None
