"""Pluggable OCR engines.

Selection (settings.ocr_engine):
  auto  — RapidOCR if installed, else engines degrade gracefully
          (uploads land in PENDING_OCR, retryable via the reprocess API)
  rapid — RapidOCR (PaddleOCR models in ONNX; CPU; works on py3.14/macOS/Linux)
  paddle— full PaddleOCR pipeline for linux workers (see Dockerfile.ocr)
  test  — deterministic fixture engine for CI

Scanned PDFs are rasterized with pypdfium2 before recognition.
"""

from typing import Any, Protocol, Optional, Tuple
import numpy as np
import cv2

from app.core.config import settings


class OcrEngine(Protocol):
    def extract_tables(self, data: bytes, content_type: str) -> list[Any]:
        """Returns RawTable-compatible objects."""
        ...

    def available(self) -> bool: ...


class OcrUnavailableError(Exception):
    pass


# --- table region detection (before OCR) ----------------------------------------

def detect_table_region(image: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """
    Detect the bordered data table region in a page image.

    Returns (x1, y1, x2, y2) crop coordinates, or None if no table found.
    Finds the largest contiguous region with BOTH dense horizontal and vertical lines,
    which corresponds to the actual data table grid (not page chrome).
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image

    # Threshold to binary (inverted: lines are white)
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

    # Detect horizontal lines (table rows) - kernel wide enough to span columns
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (min(50, gray.shape[1] // 10), 1))
    h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)
    h_projection = np.sum(h_lines > 0, axis=1)

    # Detect vertical lines (table columns) - kernel tall enough to span rows
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, min(30, gray.shape[0] // 10)))
    v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)
    v_projection = np.sum(v_lines > 0, axis=0)

    # Threshold for "dense" lines
    h_thresh = max(10, gray.shape[1] * 0.01)
    v_thresh = max(10, gray.shape[0] * 0.01)
    h_dense_mask = h_projection > h_thresh
    v_dense_mask = v_projection > v_thresh

    # Find contiguous horizontal bands with dense lines
    h_bands = []
    in_band = False
    band_start = 0
    for y, dense in enumerate(h_dense_mask):
        if dense and not in_band:
            in_band = True
            band_start = y
        elif not dense and in_band:
            in_band = False
            h_bands.append((band_start, y - 1))
    if in_band:
        h_bands.append((band_start, len(h_dense_mask) - 1))

    # For each horizontal band, check vertical line consistency and score
    best_region = None
    best_score = 0

    for y1, y2 in h_bands:
        band_height = y2 - y1 + 1
        if band_height < 10:  # Too small to be a table
            continue

        # Check vertical lines in this band
        band_v = v_lines[y1:y2+1, :]
        v_sum = np.sum(band_v > 0, axis=0)
        v_dense_in_band = np.where(v_sum > band_height * 0.3)[0]  # Lines spanning 30% of band

        if len(v_dense_in_band) < 5:  # Need at least 5 vertical lines
            continue

        x1 = int(v_dense_in_band[0])
        x2 = int(v_dense_in_band[-1])
        table_width = x2 - x1
        table_height = band_height

        # Score: prefer wider tables with more vertical lines and reasonable height
        # Width score (normalized), vertical line count, height score
        width_score = table_width / gray.shape[1]
        v_line_score = min(len(v_dense_in_band) / 50.0, 1.0)  # Cap at 50 lines
        height_score = min(table_height / (gray.shape[0] * 0.5), 1.0)  # Prefer tables up to 50% height

        score = width_score * v_line_score * height_score

        if score > best_score:
            best_score = score
            best_region = (x1, y1, x2, y2)

    if best_region is None:
        return None

    x1, y1, x2, y2 = best_region

    # Extend downward to include data rows until the next major horizontal band
    # (which is typically the legend/footer). Find the next CONTIGUOUS dense
    # horizontal band after the table header that is separated by a gap.
    # A "major band" = multiple consecutive rows with dense horizontal lines.
    next_band_y = None
    in_gap = False
    gap_start = y2
    
    for y in range(y2 + 1, gray.shape[0]):
        if h_projection[y] > h_thresh:
            if in_gap:
                # End of gap, start of potential new band
                gap_height = y - gap_start
                if gap_height > 20:  # Significant gap before this band
                    # Check if this is a contiguous band (multiple dense lines)
                    band_end = y
                    while band_end + 1 < gray.shape[0] and h_projection[band_end + 1] > h_thresh:
                        band_end += 1
                    band_height = band_end - y + 1
                    if band_height > 5:  # Major band has multiple lines
                        next_band_y = y
                        break
                in_gap = False
        else:
            if not in_gap:
                in_gap = True
                gap_start = y
    
    if next_band_y is not None:
        y2 = next_band_y  # Extend to just before the next major band (legend)
    else:
        y2 = gray.shape[0]  # Extend to bottom of image

    # Width from horizontal rules: vertical separators can be sparse or short on
    # one side of wide grids (e.g. GETS day columns 25–31), and row rules can be
    # shorter than the main h-line kernel (47px day cells vs a 50px kernel) —
    # so measure width with a looser kernel over the FULL vertical extent.
    h_loose = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (16, 1))
    )
    band_h = h_loose[y1:y2 + 1, :]
    hs_xs = np.where(band_h > 0)[1]
    if hs_xs.size:
        x1, x2 = min(x1, int(hs_xs.min())), max(x2, int(hs_xs.max()))

    # Add small padding
    pad_x = max(5, (x2 - x1) * 0.02)
    pad_y = max(5, (y2 - y1) * 0.02)
    x1 = max(0, x1 - int(pad_x))
    y1 = max(0, y1 - int(pad_y))
    x2 = min(gray.shape[1], x2 + int(pad_x))
    y2 = min(gray.shape[0], y2 + int(pad_y))

    # Require reasonable table size (at least 20% of image width, 10% height)
    if (x2 - x1) < gray.shape[1] * 0.2 or (y2 - y1) < gray.shape[0] * 0.1:
        return None

    return (x1, y1, x2, y2)


def crop_to_table(image: np.ndarray) -> np.ndarray:
    """Crop image to detected table region, or return original if no table found."""
    region = detect_table_region(image)
    if region is None:
        return image
    x1, y1, x2, y2 = region
    return image[y1:y2, x1:x2]


# --- colored-cell digit recovery -----------------------------------------------
# Fully-filled grid cells (e.g. magenta GETS hours) defeat text detectors:
# white text on saturated fill doesn't emit a text box. Detect the blobs and
# read each digit with tesseract (proven path from the standalone extractor).

def _hsv_fill_mask(image: np.ndarray) -> np.ndarray:
    """Strongly-colored fill pixels (any hue; neutral chrome excluded)."""
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    sat = hsv[..., 1].astype(np.int16)
    val = hsv[..., 2].astype(np.int16)
    return ((sat > 60) & (val > 60)).astype(np.uint8) * 255


def _read_fill_digit(image: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> str | None:
    """Read the digit inside one filled cell: fill pixels are the background,
    text is whatever's far from the dominant fill color (green channel splits
    magenta well; fallback to luminance)."""
    try:
        import pytesseract
    except ImportError:
        return None
    h, w = image.shape[:2]
    x0, x1 = max(0, x0), min(w, x1 + 1)
    y0, y1 = max(0, y0), min(h, y1 + 1)
    seg = image[y0:y1, x0:x1]
    if seg.size == 0:
        return None
    g = seg[..., 1].astype(np.float32)
    # white text (255) vs magenta fill (54); if dark text, flip the vote
    text_mask = g > 140 if (g > 140).sum() >= (g < 40).sum() else g < 40
    img = np.where(text_mask, 0, 255).astype(np.float32)
    big = cv2.resize(img, None, fx=10, fy=10, interpolation=cv2.INTER_CUBIC)
    big = cv2.erode(big, np.ones((2, 2), np.uint8))  # pinhead strokes thicken
    big = cv2.copyMakeBorder(big, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)
    t = pytesseract.image_to_string(
        big.astype(np.uint8),
        config="--psm 8 -c tessedit_char_whitelist=0123456789",
    ).strip()
    return t if t.isdigit() else None


def detect_filled_cell_lines(image: np.ndarray) -> list[tuple[list[list[float]], str, float]]:
    """Synthetic OCR lines for filled grid cells: (box, digits, confidence)."""
    mask = _hsv_fill_mask(image)
    num_labels, labels = cv2.connectedComponents(mask)
    out: list = []
    for i in range(1, num_labels):
        coords = np.where(labels == i)
        if len(coords[0]) < 100:  # pixel noise / antialiasing
            continue
        y0, y1 = int(coords[0].min()), int(coords[0].max())
        x0, x1 = int(coords[1].min()), int(coords[1].max())
        text = _read_fill_digit(image, x0, y0, x1, y1)
        if text is None:
            # filled cell we cannot read: still emit, flagged via confidence
            continue
        out.append(([  # RapidOCR-style 4-point box
            [float(x0), float(y0)], [float(x1), float(y0)],
            [float(x1), float(y1)], [float(x0), float(y1)],
        ], text, 0.97))
    return out


# --- shared post-OCR table reconstruction --------------------------------------


def reconstruct_table(lines: list[tuple[list[list[float]], str, float]]) -> list:
    """Rebuilds a logical table from word-level OCR boxes.

    Handles:
    1. Scale-safe row banding (dynamic threshold from median glyph height)
    2. Multi-row headers: combines consecutive header-like bands
    3. Many columns (e.g., 31 daily columns): uses x-position alignment
    4. Known column aliases for canonical naming
    """
    from app.services.extraction.normalize import FIELD_ALIASES, LEAVE_COLUMN_ALIASES
    from app.services.extraction.readers import RawTable

    if not lines:
        return [RawTable(headers=[], rows=[])], []

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

    # Skip leading button/navigation bands (few items, short texts like
    # "Add Project") — but ONLY when a denser band actually follows. On small
    # tables the header itself is short; eating it starves the whole table.
    header_start = 0
    has_dense_band_ahead = any(len(b) >= 5 for b in bands)
    if has_dense_band_ahead:
        while header_start < len(bands):
            band = bands[header_start]
            texts = [c["text"] for c in band]
            if len(band) <= 5 and all(len(t) < 15 for t in texts):
                header_start += 1
            else:
                break

    if header_start >= len(bands):
        return [RawTable(headers=[], rows=[])], []

    # Combine consecutive header bands (bands with many items, header-like texts)
    header_bands = []
    for i in range(header_start, len(bands)):
        band = bands[i]
        texts = [c["text"] for c in band]
        # Header bands: many items (>= 5), or contains known header keywords
        # Header bands contain known header keywords; data rows have employee codes (6+ digits)
        header_keywords = ["person", "supplier", "billable", "job", "family", "uom", "remarks",
                           "project", "sub", "id", "total", "day", "mon", "tue", "wed", "thu", "fri", "sat", "sun",
                           "select", "hours", "rate", "amount", "week", "date"]
        text_lower = " ".join(texts).lower()
        has_header_kw = any(kw in text_lower for kw in header_keywords)
        # Data row indicator: 6+ digit employee code
        has_emp_code = any(t.isdigit() and len(t) >= 6 for t in texts)
        
        if has_header_kw and not has_emp_code:
            header_bands.append(band)
        else:
            break

    if not header_bands:
        header_bands = [bands[header_start]]

    # Collect all header cells
    header_cells = []
    for band in header_bands:
        for c in band:
            header_cells.append({
                "x0": c["x0"], "x1": c["x1"],
                "xc": (c["x0"] + c["x1"]) / 2,
                "text": c["text"],
            })
    header_cells.sort(key=lambda c: c["xc"])

    # Detect daily grid spatially (gap clustering), then snap the grid origin
    # to authoritative day-number tokens so position defines the label.
    grid_gap = None
    daily_cells = []
    daily_start_xc = None
    if len(header_cells) > 1:
        gaps = [header_cells[i+1]["xc"] - header_cells[i]["xc"] for i in range(len(header_cells)-1)]
        gap_counts = {}
        for g in gaps:
            rg = round(g)
            if rg > 0:
                gap_counts[rg] = gap_counts.get(rg, 0) + 1
        for gap_size, count in sorted(gap_counts.items()):
            if count >= 10:
                grid_gap = gap_size
                in_daily = False
                for i, g in enumerate(gaps):
                    rg = round(g)
                    if rg == 0:
                        if in_daily:
                            daily_cells.append(header_cells[i+1])
                        continue
                    if abs(rg - grid_gap) <= 2:
                        if not in_daily:
                            in_daily = True
                            daily_cells.append(header_cells[i])
                        daily_cells.append(header_cells[i+1])
                    else:
                        if in_daily:
                            if rg <= 50:
                                daily_cells.append(header_cells[i+1])
                                continue
                            break
                break

    day_digits = sorted(
        ((c["xc"], int(c["text"])) for c in daily_cells
         if c["text"].isdigit() and 1 <= int(c["text"]) <= 31 and len(c["text"]) <= 2),
        key=lambda t: t[0],
    )
    if grid_gap and len(day_digits) >= 3:
        first_x, first_n = day_digits[0]
        daily_start_xc = first_x - (first_n - 1) * grid_gap

    # Split header cells into non-daily and daily
    non_daily_cells = []
    if grid_gap and daily_cells:
        daily_xc_set = set(round(c["xc"]) for c in daily_cells)
        non_daily_cells = [c for c in header_cells if round(c["xc"]) not in daily_xc_set]
    else:
        non_daily_cells = header_cells

    # Find column centers from non-daily header cells
    if len(non_daily_cells) <= 1:
        col_centers = [non_daily_cells[0]["xc"]] if non_daily_cells else []
    else:
        center_gaps = [non_daily_cells[i+1]["xc"] - non_daily_cells[i]["xc"] for i in range(len(non_daily_cells)-1)]
        # Ignore near-zero gaps (overlapping cells from different header rows) for median
        significant_gaps = [g for g in center_gaps if g > 10]
        center_med_gap = sorted(significant_gaps)[len(significant_gaps)//2] if significant_gaps else 50
        # Use a fixed threshold suitable for table columns (50-60px typical)
        center_threshold = min(center_med_gap * 1.2, 60)
        
        col_centers = [non_daily_cells[0]["xc"]]
        for i in range(1, len(non_daily_cells)):
            gap = non_daily_cells[i]["xc"] - non_daily_cells[i-1]["xc"]
            if gap > center_threshold:
                col_centers.append(non_daily_cells[i]["xc"])
    
    # Define column boundaries midway between centers for non-daily columns
    col_defs = []
    for i, xc in enumerate(col_centers):
        if i == 0:
            x0 = max(0, xc - (col_centers[1] - xc) / 2) if len(col_centers) > 1 else xc - 50
        elif i == len(col_centers) - 1:
            x0 = (col_centers[i-1] + xc) / 2
        else:
            x0 = (col_centers[i-1] + xc) / 2
        
        if i == len(col_centers) - 1:
            x1 = xc + (xc - col_centers[i-1]) / 2 if len(col_centers) > 1 else xc + 50
        else:
            x1 = (xc + col_centers[i+1]) / 2
        
        # Collect header texts from all bands in this column's x-range
        col_texts = []
        for band in header_bands:
            for c in band:
                c_xc = (c["x0"] + c["x1"]) / 2
                if x0 <= c_xc < x1:
                    col_texts.append(c["text"])
        
        label = " ".join(col_texts) if col_texts else f"col_{i}"
        col_defs.append({"label": label, "x0": x0, "x1": x1, "xc": xc})

    # Daily columns: positions anchored to the detected day-1; labels by grid
    # index (never the digit OCR read), weekday attached on center overlap.
    if grid_gap and daily_cells:
        start_xc = daily_start_xc if daily_start_xc is not None else min(
            c["xc"] for c in daily_cells
        )
        end_xc = max(c["xc"] for c in daily_cells)
        n_days = max(1, int(round((end_xc - start_xc) / grid_gap)) + 1)
        n_days = min(n_days, 31)
        for d in range(n_days):
            xc = start_xc + d * grid_gap
            x0, x1 = xc - grid_gap / 2, xc + grid_gap / 2
            weekday = next(
                (c["text"] for c in daily_cells
                 if x0 <= c["xc"] < x1
                 and c["text"] in ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")),
                None,
            )
            label = f"Day {d + 1}" + (f" ({weekday})" if weekday else "")
            col_defs.append({"label": label, "x0": x0, "x1": x1, "xc": xc})

        # Same-pitch column(s) right of the daily grid (e.g. Total): add them
        # instead of letting the day grid swallow them.
        for c in header_cells:
            if c["xc"] > start_xc + n_days * grid_gap and \
                    all(not (cd["x0"] <= c["xc"] < cd["x1"]) for cd in col_defs):
                col_defs.append({
                    "label": c["text"],
                    "x0": col_defs[-1]["x1"],
                    "x1": c["xc"] + grid_gap / 2,
                    "xc": c["xc"],
                })

    # Normalize column labels using known aliases
    phrases = sorted(
        {a.lower() for m in (FIELD_ALIASES, LEAVE_COLUMN_ALIASES)
         for alts in m.values() for a in alts},
        key=len, reverse=True,
    )
    for col in col_defs:
        # Try to match known aliases
        tokens = col["label"].lower().split()
        for phrase in phrases:
            if phrase in col["label"].lower():
                col["label"] = phrase
                break

    # Assign data cells to columns by x-center
    boundaries = [(col_defs[i]["x1"] + col_defs[i+1]["x0"]) / 2 for i in range(len(col_defs) - 1)]

    def assign_col(x_center: float) -> int:
        for bi, b in enumerate(boundaries):
            if x_center < b:
                return bi
        return len(col_defs) - 1

    # Process data bands (everything after header bands)
    data_bands = bands[header_start + len(header_bands):]

    rows_out: list[list[str]] = []
    confidences: list[float | None] = []
    band_texts = [" ".join(c["text"] for c in band) for band in bands]

    for band in data_bands:
        cells: list[str | None] = [None] * len(col_defs)
        cell_confs: dict[int, float] = {}
        for c in band:
            ci = assign_col((c["x0"] + c["x1"]) / 2)
            cells[ci] = f"{cells[ci]} {c['text']}".strip() if cells[ci] else c["text"]
            cell_confs[ci] = min(cell_confs.get(ci, 1.0), c["conf"])
        # Wide tables: single-cell bands are usually chrome (footer/legend).
        # Narrow tables: a lone populated cell is a legitimate row — keep it.
        min_populated = 2 if len(col_defs) >= 3 else 1
        if sum(1 for c in cells if c and c.strip()) >= min_populated:
            rows_out.append([(c or "") for c in cells])
            confidences.append(min(cell_confs.values()) if cell_confs else None)

    table = RawTable(headers=[c["label"] for c in col_defs], rows=rows_out)
    table.row_confidences = confidences
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
    # Don't fallback for wide tables (timesheets, etc.) - they have their own schema
    is_wide_table = len(table.headers) >= 6
    if headers_ok and not starved_rows:
        return tables
    if is_wide_table and not starved_rows:
        return tables  # Preserve wide table structure

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
        for page_idx, image in enumerate(pages):
            img_np = np.asarray(image)
            # Crop to table region before OCR to avoid page chrome
            cropped = crop_to_table(img_np)
            result, _elapsed = engine(cropped)
            for box, text, conf in result or []:
                all_lines.append((box, str(text), float(conf)))
            # Filled cells carry numbers invisible to text detection
            all_lines.extend(detect_filled_cell_lines(cropped))
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
