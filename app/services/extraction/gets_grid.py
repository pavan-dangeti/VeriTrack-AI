"""GETS timesheet reader: geometry first, OCR second, totals-verified.

GETS screenshots come from a web app, so the layout is regular. The reader finds the day input
boxes and ruling lines to get the exact cell grid, OCRs the text columns and page header as
regions, recognises each inked day cell individually, classifies cell fill colours, then
cross-checks every value against the sheet's printed totals and repairs cells the constraints
pin down. Detecting every tiny digit with a text detector instead misses most of them.
"""

from __future__ import annotations

import calendar
import itertools
import re
import threading
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Any

import cv2
import numpy as np

TARGET_BOX_HEIGHT = 24.0  # px — reference height of a day input box
MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
WEEKDAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")

TEXT_COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("select", ("select",)),
    ("person_id", ("person id",)),
    ("supplier", ("supplier",)),
    ("job_family", ("billable job family", "job family")),
    ("uom", ("uom",)),
    ("project_id", ("project id",)),
    ("sub_project", ("sub project",)),
    ("sub_project_id", ("sub project id",)),
    ("remarks", ("remarks",)),
)
# "Good Day, NAME" — tolerant of OCR slips like 'G00d Day' / 'Good Dav'
_GREETING = re.compile(r"g\W?[o0]{1,2}\W?d\s*d\W?[a@4]\W?[yv]\s*[,.:;]?\s*(.+)$", re.IGNORECASE)
_GREETING_ONLY = re.compile(r"g\W?[o0]{1,2}\W?d\s*d\W?[a@4]\W?[yv]\s*[,.:;]?", re.IGNORECASE)
SPLIT_SCORE = 0.8499  # marker confidence for text split across columns by char position
_LABELS = sorted(
    ((key, alias.replace(" ", "")) for key, aliases in TEXT_COLUMNS for alias in aliases),
    key=lambda kv: -len(kv[1]),
)

class GetsLayoutError(Exception):
    """The image is not a recognisable GETS timesheet."""


@dataclass
class GetsCell:
    day: int
    hours: float | None
    status: str  # EMPTY | USER_SIGNED | PM_APPROVED | LM_APPROVED | PLANNED | FILLED
    raw: str = ""
    confidence: float = 1.0
    corrected: bool = False


@dataclass
class GetsLine:
    row_index: int
    person_id: str = ""
    supplier: str = ""
    job_family: str = ""
    uom: str = ""
    project_id: str = ""
    sub_project: str = ""
    sub_project_id: str = ""
    remarks: str = ""
    cells: list[GetsCell] = field(default_factory=list)
    printed_total: float | None = None
    confidence: float = 1.0
    issues: list[str] = field(default_factory=list)

    @property
    def hours_by_day(self) -> dict[int, float]:
        return {c.day: c.hours for c in self.cells if c.hours is not None}

    @property
    def computed_total(self) -> float:
        total = round(sum(self.hours_by_day.values()), 2)
        return int(total) if float(total).is_integer() else total

    @property
    def is_out_of_office(self) -> bool:
        name = re.sub(r"[^a-z]", "", self.sub_project.lower())
        return "outofoffice" in name


@dataclass
class GetsSheet:
    employee_name: str = ""
    person_id: str = ""
    supplier: str = ""
    job_family: str = ""
    month: int | None = None
    year: int | None = None
    days_in_month: int = 0
    weekdays: list[str] = field(default_factory=list)
    lines: list[GetsLine] = field(default_factory=list)
    totals: dict[str, list[float | None]] = field(default_factory=dict)
    totals_printed_total: dict[str, float | None] = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return bool(self.checks) and all(c["ok"] for c in self.checks)

    @property
    def status(self) -> str:
        if not self.verified:
            return "NEEDS_REVIEW"
        return "CORRECTED" if self.corrections else "VERIFIED"

    @property
    def confidence(self) -> float:
        if not self.lines:
            return 0.0
        base = min(line.confidence for line in self.lines)
        if self.verified:
            # arithmetic agreement with the printed totals is strong evidence
            base = max(base, 0.95)
        return round(min(base, 0.6) if not self.verified else base, 3)

    @property
    def period(self) -> str | None:
        if self.year and self.month:
            return f"{self.year:04d}-{self.month:02d}"
        return None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(status=self.status, verified=self.verified,
                    confidence=self.confidence, period=self.period)
        for line_dict, line in zip(data["lines"], self.lines, strict=True):
            line_dict["computed_total"] = line.computed_total
            line_dict["is_out_of_office"] = line.is_out_of_office
        return data


class _EnginePool:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._free: list[Any] = []
        self._created = 0

    @staticmethod
    def _size() -> int:
        from app.core.config import settings

        return max(1, int(getattr(settings, "ocr_concurrency", 2)))

    def acquire(self):
        with self._cond:
            while not self._free and self._created >= self._size():
                self._cond.wait()
            if self._free:
                return self._free.pop()
            self._created += 1
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover - depends on install
            with self._cond:
                self._created -= 1
                self._cond.notify()
            from app.services.extraction.ocr import OcrUnavailableError

            raise OcrUnavailableError(
                "RapidOCR is not installed (pip install rapidocr-onnxruntime)"
            ) from exc
        # 'max' limit: never upscale regions (the default 'min' blows a 250px
        # strip up to 736px+ and costs 2-3x the time for no accuracy gain)
        return RapidOCR(det_limit_type="max", det_limit_side_len=2000)

    def release(self, engine) -> None:
        with self._cond:
            self._free.append(engine)
            self._cond.notify()


ENGINE_POOL = _EnginePool()


def warm_up_ocr() -> None:
    try:
        ENGINE_POOL.release(ENGINE_POOL.acquire())
    except Exception:  # noqa: BLE001, S110 — OCR missing: uploads go PENDING_OCR
        pass


def _pad(crop: np.ndarray, frac: float = 0.35) -> np.ndarray:
    """Pads a crop with its own border colour — recognisers want context."""
    if crop.size == 0:
        return np.full((32, 32, 3), 255, np.uint8)
    edge = np.concatenate([crop[0], crop[-1], crop[:, 0], crop[:, -1]])
    color = tuple(int(v) for v in np.median(edge, axis=0))
    pad = max(4, int(crop.shape[0] * frac))
    return cv2.copyMakeBorder(crop, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=color)


# The recogniser sometimes emits full-width forms ('（', '，', 'Ａ'); map them to
# ASCII one-for-one so character positions stay aligned.
_FULLWIDTH = {cp: cp - 0xFEE0 for cp in range(0xFF01, 0xFF5F)} | {0x3000: 0x20}


def _ascii(text: str) -> str:
    return text.translate(_FULLWIDTH)


class _Ocr:
    def __init__(self, engine) -> None:
        self.engine = engine

    def detect(self, image: np.ndarray, *, offset=(0, 0), scale: float = 1.0) -> list[dict]:
        """Det + rec over a region. Coordinates are mapped back through
        `scale` and `offset`; every token keeps char-level x positions."""
        if image.size == 0 or min(image.shape[:2]) < 8:
            return []
        work = image
        if scale != 1.0:
            work = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        result, _ = self.engine(work, return_word_box=True)
        ox, oy = offset
        tokens = []
        for item in result or []:
            box, text, score = item[0], _ascii(str(item[1])), float(item[2])
            xs = [p[0] / scale + ox for p in box]
            ys = [p[1] / scale + oy for p in box]
            chars: list[tuple[str, float]] = []
            if len(item) >= 5 and item[3] and item[4]:
                for cbox, ch in zip(item[3], item[4], strict=False):
                    cx = sum(p[0] for p in cbox) / len(cbox) / scale + ox
                    chars.append((_ascii(ch), cx))
            angle = float(np.degrees(np.arctan2(box[1][1] - box[0][1], box[1][0] - box[0][0])))
            tokens.append({
                "text": text.strip(), "score": score,
                "x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys),
                "yc": (min(ys) + max(ys)) / 2, "chars": chars, "angle": angle,
            })
        return tokens

    def recognize(self, crops: list[np.ndarray]) -> list[tuple[str, float]]:
        if not crops:
            return []
        prepared = []
        for c in crops:
            if c.size and c.shape[0] < 28:
                # small glyphs: the recogniser (48 px input) reads '0' as '。'
                f = 28 / max(1, c.shape[0])
                c = cv2.resize(c, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
            prepared.append(_pad(c))
        results, _ = self.engine.text_rec(prepared)
        return [(_ascii(str(t)), float(s)) for t, s in results]


def _find_day_boxes(rgb: np.ndarray) -> list[tuple[int, int, int, int]]:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    binary = (gray < 215).astype(np.uint8) * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects = [cv2.boundingRect(c) for c in contours]
    return [r for r in rects if 10 <= r[3] <= 120 and 12 <= r[2] <= 170
            and 1.0 <= r[2] / r[3] <= 2.2]


def _cluster(values: list[float], tol: float) -> list[list[int]]:
    """Groups indices whose sorted neighbours are within `tol`."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    groups: list[list[int]] = []
    for i in order:
        if groups and values[i] - values[groups[-1][-1]] <= tol:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


@dataclass
class _Grid:
    rows: list[tuple[int, int]]                 # data rows: (y0, y1) of the day boxes
    cols: list[tuple[int, int]]                 # day columns: (x0, x1) of the day boxes
    boxes: dict[tuple[int, int], tuple[int, int, int, int]]  # (row, col) -> exact rect
    box_h: float
    pitch: float
    table: tuple[int, int, int, int]            # x0, y0, x1, y1
    hlines: list[int]
    vlines: list[int]


def _lattice_from(rects):
    if len(rects) < 20:
        return None
    med_h = float(np.median([r[3] for r in rects]))
    med_w = float(np.median([r[2] for r in rects]))
    ycs = [r[1] + r[3] / 2 for r in rects]
    row_groups = [g for g in _cluster(ycs, med_h * 0.4) if len(g) >= 20]
    if not row_groups:
        return None
    members = [i for g in row_groups for i in g]
    xcs_all = {i: rects[i][0] + rects[i][2] / 2 for i in members}
    xcs = [xcs_all[i] for i in members]
    col_groups = _cluster(xcs, med_w * 0.4)
    min_support = max(1, len(row_groups) // 2)
    col_centres = sorted(
        float(np.median([xcs[j] for j in g])) for g in col_groups if len(g) >= min_support
    )
    if len(col_centres) < 20:
        return None
    pitch = float(np.median(np.diff(col_centres)))
    runs: list[list[float]] = [[col_centres[0]]]
    for prev, cur in zip(col_centres, col_centres[1:], strict=False):
        if abs((cur - prev) - pitch) <= 0.25 * pitch:
            runs[-1].append(cur)
        else:
            runs.append([cur])
    col_centres = max(runs, key=len)[:31]
    if len(col_centres) < 20:
        return None
    cols = [(int(round(c - med_w / 2)), int(round(c + med_w / 2))) for c in col_centres]
    rows: list[tuple[int, int]] = []
    boxes: dict[tuple[int, int], tuple[int, int, int, int]] = {}
    for ri, g in enumerate(sorted(row_groups, key=lambda g: np.median([ycs[i] for i in g]))):
        yc = float(np.median([ycs[i] for i in g]))
        rows.append((int(round(yc - med_h / 2)), int(round(yc + med_h / 2))))
        for i in g:
            ci = int(np.argmin([abs(xcs_all[i] - c) for c in col_centres]))
            if abs(xcs_all[i] - col_centres[ci]) <= 0.3 * pitch:
                boxes[(ri, ci)] = rects[i]
    return rows, cols, boxes, med_h, pitch


def _box_lattice(rgb: np.ndarray):
    """Day-box lattice, or None. Page chrome also yields box-like contours
    (glyphs, checkboxes, buttons), so the day boxes are identified as the
    size cluster that lines up into rows of ≥20 evenly pitched boxes."""
    rects = _find_day_boxes(rgb)
    if len(rects) < 20:
        return None
    bins: dict[tuple[int, int], int] = {}
    for _, _, w, h in rects:
        key = (int(round(w / 3)), int(round(h / 3)))
        bins[key] = bins.get(key, 0) + 1
    best = None
    for (bw, bh), _n in sorted(bins.items(), key=lambda kv: -kv[1])[:8]:
        w0, h0 = bw * 3, bh * 3
        sel = [r for r in rects if abs(r[2] - w0) <= 0.2 * w0 + 3 and abs(r[3] - h0) <= 0.2 * h0 + 3]
        lattice = _lattice_from(sel)
        if lattice is None:
            continue
        score = len(lattice[0]) * len(lattice[1]) + (1000 if 28 <= len(lattice[1]) <= 31 else 0)
        if best is None or score > best[0]:
            best = (score, lattice)
    return best[1] if best else None


def _estimate_scale(rgb: np.ndarray) -> float:
    lattice = _box_lattice(rgb)
    if lattice is not None:
        return TARGET_BOX_HEIGHT / lattice[3]
    # very small captures: boxes may not close — probe an enlarged copy
    big = cv2.resize(rgb, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    lattice = _box_lattice(big)
    return TARGET_BOX_HEIGHT / (lattice[3] / 2) if lattice else 1.0


def _normalise_scale(rgb: np.ndarray) -> np.ndarray:
    """Small captures are enlarged to the reference box height (OCR needs the
    pixels); larger ones (HiDPI, 125–200 % zoom) keep their resolution unless
    huge — downsampling text only ever costs accuracy."""
    scale = _estimate_scale(rgb)
    if scale > 1.08:
        return cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if scale < 0.55:
        f = scale * 1.5
        return cv2.resize(rgb, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    return rgb


def _locate_grid(rgb: np.ndarray) -> _Grid:
    lattice = _box_lattice(rgb)
    if lattice is None:
        raise GetsLayoutError("no timesheet day grid found in the image")
    rows, cols, boxes, box_h, pitch = lattice
    table, hlines, vlines = _table_rulings(rgb, rows, cols, box_h, pitch)
    return _Grid(rows=rows, cols=cols, boxes=boxes, box_h=box_h, pitch=pitch,
                 table=table, hlines=hlines, vlines=vlines)


def _runs(mask_1d: np.ndarray, min_len: int = 1) -> list[tuple[int, int]]:
    out, start = [], None
    for i, on in enumerate(mask_1d):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    if start is not None and len(mask_1d) - start >= min_len:
        out.append((start, len(mask_1d)))
    return out


def _run_centres(values: list[int]) -> list[int]:
    out: list[list[int]] = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= 2:
            out[-1].append(v)
        else:
            out.append([v])
    return [int(round((g[0] + g[-1]) / 2)) for g in out]


def _table_rulings(rgb, rows, cols, box_h, pitch):
    """Long light ruling lines around the grid → table extent + separators.
    The line threshold adapts to the page background (lines are only ~15
    grey levels darker than the table fill)."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    H, W = gray.shape
    grid_x0, grid_x1 = cols[0][0], cols[-1][1]
    grid_y0, grid_y1 = rows[0][0], rows[-1][1]
    bg = float(np.median(gray[max(0, grid_y0 - int(box_h)):grid_y1, max(0, grid_x0 - 300):grid_x0]))
    thr = bg - 5
    # average along the line direction first (noise/JPEG break thin lines
    # pixel-wise, not their mean); a 3-px min across it tolerates rulings
    # that resampling smeared over two pixel rows
    hsmooth = cv2.erode(cv2.blur(gray, (9, 1)), np.ones((3, 1), np.uint8))
    vsmooth = cv2.erode(cv2.blur(gray, (1, 9)), np.ones((1, 3), np.uint8))
    hmask = (hsmooth < thr).astype(np.uint8) * 255
    mask = (vsmooth < thr).astype(np.uint8) * 255

    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(60, int((grid_x1 - grid_x0) * 0.3)), 1))
    hmask = cv2.morphologyEx(hmask, cv2.MORPH_OPEN, hk)
    hlines: list[int] = []
    for y in np.where(hmask[:, grid_x0:grid_x1].sum(1) > 0)[0]:
        xs = np.where(hmask[y] > 0)[0]
        if xs.min() <= grid_x0 and xs.max() >= grid_x1:
            hlines.append(int(y))
    # A row of day boxes smooths into a pseudo-'line' along its borders. Real
    # rulings run on into the text columns left of the grid; box chains stop
    # at the first day. Without a visible text block, fall back to checking
    # the gaps *between* boxes (dark only for a real ruling).
    lead = int(1.5 * box_h)
    gaps = [(cols[i][1] + 1, cols[i + 1][0]) for i in range(len(cols) - 1)
            if cols[i + 1][0] - cols[i][1] >= 3]

    def is_ruling(y: int) -> bool:
        if grid_x0 - lead > 2:
            return bool(hmask[y, grid_x0 - lead:grid_x0].all())
        if not gaps or not any(r0 - 4 <= y <= r1 + 4 for r0, r1 in rows):
            return True
        vals = [int(gray[max(0, y - 1):y + 2, a:b].min(axis=0).max()) for a, b in gaps]
        return float(np.median(vals)) < thr

    hlines = _run_centres([y for y in hlines if is_ruling(y)])

    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, int((grid_y1 - grid_y0) * 0.8))))
    vmask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, vk)
    band = vmask[grid_y0:grid_y1 + 1]
    vlines: list[int] = []
    extents: dict[int, tuple[int, int]] = {}
    for x in _run_centres([int(x) for x in np.where(band.sum(0) > 0)[0]]):
        runs = _runs(vmask[:, x] > 0)
        run = next(((a, b) for a, b in runs if a <= grid_y0 + 1 <= b), None)
        # column rulings run up through the header; dropdown/box edges don't
        if run is None or run[0] > grid_y0 - 0.5 * box_h:
            continue
        vlines.append(x)
        extents[x] = run

    above = [y for y in hlines if y < grid_y0]
    below = [y for y in hlines if y > grid_y1]
    if len(above) >= 2:
        top = above[-2]
        if above[-1] - above[-2] < 0.8 * box_h and len(above) >= 3:
            top = above[-3]
    else:
        top = max(0, grid_y0 - int(2.4 * box_h))
    bottom = below[-1] if below else min(H - 1, grid_y1 + int(4.5 * box_h))
    # table rulings stop at the table; page borders run much further
    span = bottom - top
    table_v = [x for x in vlines if extents[x][0] >= top - 0.3 * span and extents[x][1] <= bottom + 0.3 * span]
    left_lines = [x for x in table_v if x < grid_x0]
    right_lines = [x for x in table_v if x > grid_x1]
    left = left_lines[0] if left_lines else 0
    # the Total column's right ruling: the last one within ~3 pitches
    near_right = [x for x in right_lines if x - grid_x1 <= 3 * pitch]
    right = near_right[-1] if near_right else min(W - 1, grid_x1 + int(2 * pitch))
    if right - grid_x1 < 0.8 * pitch:
        right = min(W - 1, grid_x1 + int(2 * pitch))
    return (int(left), int(top), int(right), int(bottom)), hlines, table_v


def _classify_fill(rgb_color) -> str:
    r, g, b = (float(v) for v in rgb_color)
    hsv = cv2.cvtColor(np.uint8([[[r, g, b]]]), cv2.COLOR_RGB2HSV)[0, 0]
    hue, sat, val = int(hsv[0]) * 2, int(hsv[1]), int(hsv[2])
    if sat > 90 and val > 60:
        if hue >= 280 or hue <= 20:
            return "USER_SIGNED"   # magenta / crimson
        if 190 <= hue < 280:
            return "PLANNED"       # blue
        if 20 < hue <= 75:
            return "PM_APPROVED"
        return "FILLED"
    if sat > 20 and 30 <= hue <= 75 and val > 200:
        return "PM_APPROVED"       # pale yellow
    if sat <= 20 and val < 246:
        return "LM_APPROVED"       # light grey
    return "EMPTY"


def _glyphs(region: np.ndarray, min_height_frac: float = 0.25):
    """(fill colour, glyph mask, bbox) for a cell. Ink = pixels far from the
    dominant fill; connected components that are border remnants (thin and
    hugging an edge) or specks (JPEG/noise) are discarded."""
    pix = region.reshape(-1, 3).astype(np.int32)
    fill = np.median(pix, axis=0)
    dist = np.sqrt(((region.astype(np.int32) - fill) ** 2).sum(axis=2))
    ink = (dist > 80).astype(np.uint8)
    h, w = ink.shape
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    keep = np.zeros_like(ink, dtype=bool)
    min_area = max(3, int(0.006 * h * w))
    for i in range(1, n):
        x, y, cw, ch, area = stats[i]
        if area < min_area:
            continue
        touches_lr = x == 0 or x + cw >= w
        touches_tb = y == 0 or y + ch >= h
        if touches_lr and cw <= 2:
            continue                       # vertical border remnant
        if touches_tb and ch <= 2:
            continue                       # horizontal border remnant
        if ch >= 0.92 * h and cw <= 3:
            continue                       # a ruling through the cell
        if ch < min_height_frac * h and cw < min_height_frac * h:
            continue                       # speck
        keep |= labels == i
    ys, xs = np.where(keep)
    if ys.size == 0:
        return fill, keep, None
    return fill, keep, (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def _clean_crop(region: np.ndarray, fill, mask: np.ndarray, bbox, pad: int = 2) -> np.ndarray:
    """Glyph crop with everything that is not the glyphs (box borders, JPEG
    specks, neighbouring rulings) painted over with the fill colour."""
    bx0, by0, bx1, by1 = bbox
    ya, yb = max(0, by0 - pad), by1 + pad + 1
    xa, xb = max(0, bx0 - pad), bx1 + pad + 1
    crop = region[ya:yb, xa:xb].copy()
    near = cv2.dilate(mask[ya:yb, xa:xb].astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    crop[~near] = np.asarray(fill, dtype=np.uint8)
    return crop


_NUM_RE = re.compile(r"^\d{1,3}(?:[.,]\d{1,2})?$")
_OCR_DIGIT_FIXES = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "。": "0", "〇": "0",
                                  "°": "0", "º": "0", "l": "1", "I": "1",
                                  "|": "1", "i": "1", "S": "5", "s": "5", "B": "8", "g": "9",
                                  "Z": "2", "z": "2", "b": "6", "G": "6", "T": "7"})


def parse_number(text: str) -> float | None:
    """Numeric cell text → number (ints stay ints). Common OCR letter/digit
    confusions are repaired; anything else is rejected, never guessed."""
    t = (text or "").strip().replace(" ", "").strip("[](){}")
    if not t:
        return None
    if not _NUM_RE.match(t):
        t2 = t.translate(_OCR_DIGIT_FIXES)
        if not _NUM_RE.match(t2):
            return None
        t = t2
    try:
        value = float(t.replace(",", "."))
    except ValueError:
        return None
    return int(value) if value.is_integer() else value


def _fmt(v: float | None) -> str:
    if v is None:
        return ""
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def _fuzzy(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _parse_labels(chars: list[tuple[str, float]]) -> list[tuple[str, float, float]]:
    """Greedy left-to-right parse of header characters into known column
    labels (longest label first, small OCR slips tolerated)."""
    compact = [(ch.lower(), x) for ch, x in chars if ch.strip() and ch.isalnum()]
    s = "".join(c for c, _ in compact)
    out: list[tuple[str, float, float]] = []
    p = 0
    while p < len(s):
        best = None
        for key, label in _LABELS:
            cand = s[p:p + len(label)]
            if len(cand) < len(label) - 1:
                continue
            score = 1.0 if cand == label else _fuzzy(cand, label)
            if score >= (0.84 if len(label) > 5 else 0.99) and (best is None or score > best[2] + 0.02):
                best = (key, len(label), score)
        if best:
            key, n, _ = best
            end = min(p + n, len(compact)) - 1
            out.append((key, compact[p][1], compact[end][1]))
            p += n
        else:
            p += 1
    return out


def _restore_spaces(tok: dict, gray: np.ndarray) -> None:
    """Re-inserts word spaces the recogniser dropped ('CAEModeler'): a blank
    pixel gap wider than ~0.22 em between two characters is a space."""
    chars = tok["chars"]
    if len(chars) < 3:
        return
    x0, x1 = int(max(0, tok["x0"])), int(min(gray.shape[1], tok["x1"] + 1))
    y0, y1 = int(max(0, tok["y0"])), int(min(gray.shape[0], tok["y1"] + 1))
    region = gray[y0:y1, x0:x1]
    if region.size == 0:
        return
    bg = np.median(region)
    ink_cols = (np.abs(region.astype(np.int32) - bg) > 60).sum(0) > 0
    em = max(6.0, (y1 - y0) * 0.75)
    inner = [(a, b) for a, b in _runs(~ink_cols) if a > 0 and b < len(ink_cols)]
    if not inner:
        return
    typical = float(np.median([b - a for a, b in inner]))
    # a word space is wide in absolute terms, or (weaker) far wider than the letter spacing where
    # the case changes ('SeatCore')
    gaps = [(a + x0, b + x0, b - a >= max(0.24 * em, 1.7 * typical)) for a, b in inner
            if b - a >= max(0.24 * em, 1.7 * typical) or (b - a >= 0.16 * em and b - a >= 3 * typical)]
    if not gaps:
        return
    spaces = [cx for ch, cx in chars if ch == " "]
    gaps = [(a, b, st) for a, b, st in gaps if not any(abs((a + b) / 2 - sx) < em for sx in spaces)]
    if not gaps:
        return
    rebuilt: list[tuple[str, float]] = []
    for i, (ch, cx) in enumerate(chars):
        prev = rebuilt[-1][0] if rebuilt else ""
        joinable = ch not in "_-/." and prev not in "_-/." and not (ch.isdigit() and prev.isdigit())
        if i and ch != " " and prev != " " and joinable:
            prev_cx = rebuilt[-1][1]
            both_upper = prev.isupper() and ch.isupper()
            if any(prev_cx < (a + b) / 2 < cx and (st or not both_upper) for a, b, st in gaps):
                rebuilt.append((" ", (prev_cx + cx) / 2))
        rebuilt.append((ch, cx))
    if len(rebuilt) != len(chars):
        tok["chars"] = rebuilt
        tok["text"] = "".join(ch for ch, _ in rebuilt).strip()


def is_gets_screenshot(rgb: np.ndarray) -> bool:
    """Cheap layout probe (no OCR): a row of 28–31 evenly pitched day boxes."""
    try:
        grid = _locate_grid(_normalise_scale(np.ascontiguousarray(rgb[..., :3]).astype(np.uint8)))
    except GetsLayoutError:
        return False
    return 28 <= len(grid.cols) <= 31


def read_gets_sheet(image: np.ndarray) -> GetsSheet:
    rgb = _normalise_scale(np.ascontiguousarray(image[..., :3]).astype(np.uint8))
    grid = _locate_grid(rgb)
    engine = ENGINE_POOL.acquire()
    try:
        return _GetsReader(rgb, grid, _Ocr(engine)).read()
    finally:
        ENGINE_POOL.release(engine)


class _GetsReader:
    def __init__(self, rgb: np.ndarray, grid: _Grid, ocr: _Ocr) -> None:
        self.rgb = rgb
        self.gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        self.grid = grid
        self.ocr = ocr
        self.sheet = GetsSheet()
        self.day_offset = 0
        self.lines = [GetsLine(row_index=i) for i in range(len(grid.rows))]
        self.totals_bands: list[tuple[float, float]] = []
        self.totals_labels: list[str] = []
        saturation = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[..., 1]
        self.monochrome = float(np.percentile(saturation, 99.9)) < 25

    def read(self) -> GetsSheet:
        if self.monochrome:
            self.sheet.warnings.append("screenshot has no colour — approval statuses cannot be read")
        self._read_day_header()
        self.sheet.days_in_month = len(self.grid.cols) + self.day_offset
        self._read_text_block()
        self._read_day_cells()
        self._read_total_column()
        self._read_page_header()
        self._fill_sheet_identity()
        self._reconcile()
        self.sheet.lines = self.lines
        return self.sheet

    # ---- header: day numbers + weekdays -------------------------------------

    def _header_band(self) -> tuple[int, int]:
        g = self.grid
        top = g.table[1]
        first_row_top = g.rows[0][0]
        above = [y for y in g.hlines if top < y < first_row_top - 2]
        bottom = above[-1] if above and above[-1] > top + 0.8 * g.box_h else first_row_top - 3
        return top + 1, bottom

    def _read_day_header(self) -> None:
        g = self.grid
        y0, y1 = self._header_band()
        if y1 - y0 < 0.5 * g.box_h:
            return
        x0, x1 = g.cols[0][0], g.cols[-1][1]
        region = self.rgb[y0:y1, x0:x1]
        gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
        hsv = cv2.cvtColor(region, cv2.COLOR_RGB2HSV)
        ink = (gray < 170) | ((hsv[..., 1] > 100) & (hsv[..., 2] > 100))  # + red weekends
        prof = ink.sum(1) > max(2, (x1 - x0) * 0.01)
        bands = _runs(prof, min_len=max(3, int(0.15 * g.box_h)))
        if not bands:
            return
        # merge fragments closer than 2 px, keep the two tallest lines in order
        merged: list[list[int]] = []
        for a, b in bands:
            if merged and a - merged[-1][1] <= 2:
                merged[-1][1] = b
            else:
                merged.append([a, b])
        merged = sorted(sorted(merged, key=lambda ab: ab[1] - ab[0], reverse=True)[:2])
        half = g.pitch / 2
        num_band = merged[0]
        wd_band = merged[1] if len(merged) > 1 else None
        crops_num, crops_wd = [], []
        pad = 2
        # a sample is enough: day numbers only fix the column offset, and
        # 14 weekdays (two weeks) pin the calendar
        n = len(g.cols)
        sample = sorted({0, 1, 2, 3, n // 2, n - 4, n - 3, n - 2, n - 1} | set(range(min(n, 14))))
        for cx0, cx1 in (g.cols[i] for i in sample):
            xc = (cx0 + cx1) / 2
            xa, xb = int(max(0, xc - half + 1)), int(xc + half - 1)
            crops_num.append(self.rgb[max(0, y0 + num_band[0] - pad): y0 + num_band[1] + pad, xa:xb])
            if wd_band:
                crops_wd.append(self.rgb[max(0, y0 + wd_band[0] - pad): y0 + wd_band[1] + pad, xa:xb])
        nums = self.ocr.recognize(crops_num)
        wds = self.ocr.recognize(crops_wd) if crops_wd else []

        votes: dict[int, int] = {}
        for i, (t, s) in zip(sample, nums, strict=True):
            v = parse_number(t)
            if v is not None and float(v).is_integer() and s > 0.6:
                votes[int(v) - (i + 1)] = votes.get(int(v) - (i + 1), 0) + 1
        if votes:
            off, cnt = max(votes.items(), key=lambda kv: kv[1])
            if cnt >= 3 and 0 <= off <= 3:
                self.day_offset = off
            elif cnt < 3:
                self.sheet.warnings.append("day numbers in the header are unreadable; assumed day 1 first")
        read = {}
        for i, (t, _s) in zip(sample, wds, strict=False):
            t = t.strip().lower()
            best = max(WEEKDAYS, key=lambda w: _fuzzy(w.lower(), t))
            read[i] = best if _fuzzy(best.lower(), t) >= 0.5 else ""
        self.sheet.weekdays = [read.get(i, "") for i in range(n)] if read else []

    # ---- text columns --------------------------------------------------------

    def _read_text_block(self) -> None:
        g = self.grid
        x0, y0 = g.table[0], g.table[1]
        x1, y1 = g.cols[0][0] - 2, g.table[3]
        if x1 - x0 < 3 * g.box_h:
            self.sheet.warnings.append("text columns not visible in the screenshot")
            return
        tokens = self.ocr.detect(self.rgb[y0:y1, x0:x1], offset=(x0, y0))
        tokens.extend(self._recover_missed_text(tokens, x0, y0, x1, y1))
        self._rerecognize_weak(tokens)
        for tok in tokens:
            _restore_spaces(tok, self.gray)

        header_bottom = g.rows[0][0] - 0.25 * g.box_h
        columns = self._resolve_columns([t for t in tokens if t["yc"] < header_bottom], x0, x1)
        self.columns = columns
        bands = self._row_bands()
        for line, (by0, by1) in zip(self.lines, bands, strict=True):
            row_tokens = [t for t in tokens if by0 <= t["yc"] < by1]
            cells = self._cells_from_tokens(row_tokens, columns)
            cells = self._refine_low_confidence(cells, columns, by0, by1)
            self._assign_text(line, {k: v[0] for k, v in cells.items()})
            if cells:
                line.confidence = min(line.confidence, min(v[1] for v in cells.values()))

        self.totals_bands = self._totals_bands()
        for by0, by1 in self.totals_bands:
            toks = sorted((t for t in tokens if by0 <= t["yc"] < by1), key=lambda t: t["x0"])
            self.totals_labels.append(self._canon_totals_label(toks))

    def _resolve_columns(self, header_tokens, x0, x1) -> list[tuple[str, float, float]]:
        """Header labels + ruling lines → [(key, left, right)] column spans.

        Ruling lines give exact spans; the header characters inside each span
        name it. A span holding two labels (a missing ruling) is split between
        them. With no usable rulings, spans come from the labels alone.
        """
        chars: list[tuple[str, float, float]] = []  # (ch, x, y)
        for t in header_tokens:
            if t["chars"]:
                chars.extend((ch, cx, t["yc"]) for ch, cx in t["chars"])
            else:
                n = max(1, len(t["text"]))
                for i, ch in enumerate(t["text"]):
                    chars.append((ch, t["x0"] + (i + 0.5) * (t["x1"] - t["x0"]) / n, t["yc"]))

        vl = sorted(x for x in self.grid.vlines if x0 + 3 < x < x1 - 3)
        edges = [x0, *vl, x1]
        spans = [(a, b) for a, b in zip(edges, edges[1:], strict=False) if b - a > 0.6 * self.grid.box_h]
        line_h = max(4.0, 0.5 * self.grid.box_h)

        found: list[tuple[str, float, float, float, float]] = []  # key, lx0, lx1, span_l, span_r
        for a, b in spans:
            inside = [c for c in chars if a <= c[1] < b]
            inside.sort(key=lambda c: (round(c[2] / line_h), c[1]))
            labels = _parse_labels([(ch, x) for ch, x, _ in inside])
            for key, lx0, lx1 in labels:
                found.append((key, lx0, lx1, a, b))

        seen: set[str] = set()
        ordered = []
        for item in sorted(found, key=lambda f: f[1]):
            if item[0] not in seen:
                seen.add(item[0])
                ordered.append(item)
        if len(ordered) < 4:
            self.sheet.warnings.append("column header unreadable; using ruling order")
            keys = [k for k, _ in TEXT_COLUMNS]
            return [(keys[i] if i < len(keys) else f"col_{i}", float(a), float(b))
                    for i, (a, b) in enumerate(spans)]

        out: list[tuple[str, float, float]] = []
        for i, (key, lx0, lx1, a, b) in enumerate(ordered):
            left, right = a, b
            if i > 0 and ordered[i - 1][3] == a:        # shares a span with previous label
                left = (ordered[i - 1][2] + lx0) / 2
            if i + 1 < len(ordered) and ordered[i + 1][3] == a:
                right = (lx1 + ordered[i + 1][1]) / 2
            out.append((key, float(left), float(right)))
        return out

    @staticmethod
    def _cells_from_tokens(tokens, columns) -> dict[str, tuple[str, float]]:
        """Distributes tokens over columns: whole words by their centre, and a
        word straddling a boundary (missing space) by its characters."""
        def col_of(x):
            for key, left, right in columns:
                if left <= x < right:
                    return key
            return None

        pieces: dict[str, list[tuple[float, float, str, float]]] = {}
        for tok in tokens:
            words: list[list[tuple[str, float]]] = []
            if tok["chars"]:
                cur: list[tuple[str, float]] = []
                for ch, cx in tok["chars"]:
                    if ch == " ":
                        if cur:
                            words.append(cur)
                        cur = []
                    else:
                        cur.append((ch, cx))
                if cur:
                    words.append(cur)
            else:
                xc = (tok["x0"] + tok["x1"]) / 2
                words = [[(tok["text"], xc)]]
            n_chars = sum(len(w) for w in words) or 1
            per_col: dict[str | None, int] = {}
            for word in words:
                for _, cx in word:
                    k = col_of(cx)
                    per_col[k] = per_col.get(k, 0) + 1
            for word in words:
                keys = {col_of(cx) for _, cx in word}
                if len(keys) == 1:
                    key = keys.pop()
                    if key:
                        text = "".join(ch for ch, _ in word)
                        score = tok["score"]
                        # a stray 1–2 char fragment of a token that belongs to
                        # another column (detector hallucination at a cell
                        # edge): re-read this cell from its own crop
                        if len(per_col) > 1 and per_col[key] <= 2 and per_col[key] < 0.3 * n_chars:
                            score = min(score, SPLIT_SCORE)
                        pieces.setdefault(key, []).append((tok["yc"], word[0][1], text, score))
                    continue
                group: list[tuple[str, float]] = []
                gkey = None
                for ch, cx in [*word, ("", float("inf"))]:
                    k = col_of(cx) if ch else "__end__"
                    if group and k != gkey:
                        if gkey:
                            # char positions are approximate: a split piece is
                            # re-read from its own cell crop later
                            pieces.setdefault(gkey, []).append(
                                (tok["yc"], group[0][1], "".join(c for c, _ in group),
                                 min(tok["score"], SPLIT_SCORE))
                            )
                        group = []
                    gkey = k
                    if ch:
                        group.append((ch, cx))
        out: dict[str, tuple[str, float]] = {}
        for key, items in pieces.items():
            items.sort(key=lambda p: (round(p[0] / 6), p[1]))
            out[key] = (" ".join(p[2] for p in items if p[2]).strip(), min(p[3] for p in items))
        return out

    def _recover_missed_text(self, tokens, x0, y0, x1, y1) -> list[dict]:
        """Text the detector skipped (noise, faint rendering) still shows up
        as ink: find ink blobs no token covers and recognise them directly."""
        g = self.grid
        top = g.rows[0][0] - int(0.2 * g.box_h)        # data rows only
        region = self.gray[top:y1, x0:x1]
        if region.size == 0:
            return []
        bg = float(np.median(region))
        ink = (region < bg - 60).astype(np.uint8)
        k = max(3, int(0.3 * g.box_h))
        merged = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1)))
        n, _labels, stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)
        covered = [(t["x0"] - 3, t["y0"] - 3, t["x1"] + 3, t["y1"] + 3) for t in tokens]
        found, crops = [], []
        for i in range(1, n):
            bx, by, bw, bh, _area = stats[i]
            ax0, ay0 = bx + x0, by + top
            ax1, ay1 = ax0 + bw, ay0 + bh
            if not (0.3 * g.box_h <= bh <= 0.8 * g.box_h and bw >= 0.8 * g.box_h):
                continue                                  # one text line only
            if any(ax0 < c and a < ax1 and ay0 < d and b < ay1 for a, b, c, d in covered):
                continue                                  # overlaps a detected token
            found.append((ax0, ay0, ax1, ay1))
            crops.append(self.rgb[max(0, ay0 - 2):ay1 + 2, max(0, ax0 - 2):ax1 + 2])
        out = []
        for (ax0, ay0, ax1, ay1), (text, score) in zip(found, self.ocr.recognize(crops), strict=True):
            text = text.strip().lstrip("[|(").rstrip("]|)").strip()
            if len(text) < 2 or score < 0.75:
                continue
            n_ch = len(text)
            out.append({
                "text": text, "score": score, "x0": float(ax0), "x1": float(ax1),
                "y0": float(ay0), "y1": float(ay1), "yc": (ay0 + ay1) / 2,
                "chars": [(ch, ax0 + (j + 0.5) * (ax1 - ax0) / n_ch) for j, ch in enumerate(text)],
            })
        return out

    def _rerecognize_weak(self, tokens, threshold: float = 0.9) -> None:
        """Tokens the detector read unsure of get re-recognised from a tight,
        2×-upscaled crop — blur/JPEG hurt the full-region pass far more than
        a focused one."""
        weak = [t for t in tokens if t["score"] < threshold and t["x1"] - t["x0"] > 4]
        if not weak:
            return
        crops = []
        for t in weak:
            ya, yb = int(max(0, t["y0"] - 2)), int(t["y1"] + 3)
            xa, xb = int(max(0, t["x0"] - 1)), int(t["x1"] + 2)
            crop = self.rgb[ya:yb, xa:xb]
            crops.append(cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
        for t, (text, score) in zip(weak, self.ocr.recognize(crops), strict=True):
            text = text.strip().lstrip("[|(").rstrip("]|)").strip()
            if text and score > t["score"] + 0.05:
                n = len(text)
                t["text"], t["score"] = text, score
                t["chars"] = [(ch, t["x0"] + (i + 0.5) * (t["x1"] - t["x0"]) / n) for i, ch in enumerate(text)]

    def _refine_low_confidence(self, cells, columns, by0, by1):
        spans = {k: (a, b) for k, a, b in columns}
        for key in ("person_id", "supplier", "job_family", "uom", "project_id",
                    "sub_project", "sub_project_id"):
            text, score = cells.get(key, ("", 1.0))
            if key not in spans or score >= 0.9:
                continue
            a, b = spans[key]
            crop = self.rgb[int(by0) + 1:int(by1), int(a) + 1:int(b)]
            toks = self.ocr.detect(crop, offset=(int(a) + 1, int(by0) + 1), scale=2.0)
            if not toks:
                continue
            toks.sort(key=lambda t: (round(t["yc"] / (0.4 * self.grid.box_h)), t["x0"]))
            new_score = min(t["score"] for t in toks)
            new_text = " ".join(t["text"] for t in toks).strip()
            old_len, new_len = len(text.replace(" ", "")), len(new_text.replace(" ", ""))
            complete = new_len >= 0.85 * old_len or abs(score - SPLIT_SCORE) < 1e-6
            if new_score > score and complete and new_len:
                cells[key] = (new_text, new_score)
        return cells

    def _row_bands(self) -> list[tuple[float, float]]:
        """Vertical extent of each data row: the ruling lines around its day
        boxes when present (wrapped cells like 'Out Of / Office -' stay
        inside), else midway to the neighbouring rows."""
        rows, hl = self.grid.rows, self.grid.hlines
        bands = []
        for i, (y0, y1) in enumerate(rows):
            h = y1 - y0
            prev_bottom = rows[i - 1][1] if i > 0 else y0 - 1.2 * h
            next_top = rows[i + 1][0] if i + 1 < len(rows) else y1 + 1.2 * h
            above = [y for y in hl if prev_bottom - 3 <= y <= y0 + 3]
            below = [y for y in hl if y1 - 3 <= y <= next_top + 3]
            if above:
                top = above[-1]
            else:
                top = (prev_bottom + y0) / 2 if i > 0 else y0 - 0.3 * h
            if below:
                bottom = below[0]
            else:
                bottom = (y1 + next_top) / 2 if i + 1 < len(rows) else y1 + 0.3 * h
            bands.append((float(top), float(bottom)))
        return bands

    @staticmethod
    def _assign_text(line: GetsLine, values: dict[str, str]) -> None:
        line.person_id = re.sub(r"\D", "", values.get("person_id", ""))
        supplier = " ".join(w for w in values.get("supplier", "").split() if len(w) > 1)
        line.supplier = supplier.strip()
        job = re.sub(r"\s+", " ", values.get("job_family", "")).strip()
        job = " ".join(w for i, w in enumerate(job.split()) if not (len(w) == 1 and w.isalpha() and i == 0))
        line.job_family = re.sub(r"\s*-\s*", " - ", job).strip(" -")
        uom = re.sub(r"[^A-Za-z]", "", values.get("uom", "")).upper()
        if uom.endswith("V") and len(uom) > 2:   # dropdown chevron read as 'V'
            uom = uom[:-1]
        if uom.startswith("V") and len(uom) > 2:
            uom = uom[1:]
        line.uom = uom
        line.project_id = re.sub(r"\D", "", values.get("project_id", ""))
        sub = re.sub(r"\s+", " ", values.get("sub_project", "")).strip()
        sub = re.sub(r"\s*_\s*", "_", sub)
        sub = re.sub(r"(?<=[A-Za-z])[.,:;'`](?=\s)", "", sub)   # stray recogniser dots
        sub = re.sub(r"[\s\-:;.,_~]+$", "", sub)
        if _fuzzy(_norm(sub), "outofoffice") >= 0.85:
            sub = "Out Of Office"          # GETS's canonical leave project
        line.sub_project = sub
        line.sub_project_id = re.sub(r"\D", "", values.get("sub_project_id", ""))
        line.remarks = values.get("remarks", "").strip()
        if not line.person_id:
            line.issues.append("person id unreadable")

    def _totals_bands(self) -> list[tuple[float, float]]:
        """Text rows below the last data row (NC / STD / Total …)."""
        g = self.grid
        last = g.rows[-1][1]
        edges = [y for y in g.hlines if last - 3 <= y <= g.table[3] + 1]
        if edges:
            edges[0] = max(edges[0], last + 1)
        bands = [(float(a), float(b)) for a, b in zip(edges, edges[1:], strict=False)
                 if b - a >= 0.6 * g.box_h]
        if bands:
            return bands
        # no rulings: ink lines inside the day zone
        x0, x1 = g.cols[0][0], g.cols[-1][1]
        top = last + int(0.3 * g.box_h)
        region = self.gray[top: int(g.table[3]), x0:x1]
        if region.size == 0:
            return []
        prof = (region < 150).sum(1) > 3
        pad = 0.35 * g.box_h
        return [(top + a - pad, top + b + pad) for a, b in _runs(prof, min_len=3)]

    @staticmethod
    def _canon_totals_label(toks) -> str:
        if not toks:
            return ""
        full = _norm(" ".join(t["text"] for t in toks))
        last = toks[-1]["text"].strip()
        if full in ("total", "totals") or _norm(last) == "total":
            return "TOTAL"
        m = re.search(r"([A-Za-z]{2,4})\s*$", last)
        return m.group(1).upper() if m else ""

    # ---- day cells -------------------------------------------------------------

    def _cell_rect(self, ri: int, ci: int) -> tuple[int, int, int, int]:
        rect = self.grid.boxes.get((ri, ci))
        if rect is not None:
            return rect
        (x0, x1), (y0, y1) = self.grid.cols[ci], self.grid.rows[ri]
        return x0, y0, x1 - x0, y1 - y0

    def _read_day_cells(self) -> None:
        g = self.grid
        pending: list[tuple[GetsLine, GetsCell, np.ndarray]] = []
        inset = max(2, int(round(g.box_h * 0.09)))
        for ri, line in enumerate(self.lines):
            for ci in range(len(g.cols)):
                day = ci + 1 + self.day_offset
                x, y, w, h = self._cell_rect(ri, ci)
                cell = self.rgb[y + inset: y + h - inset, x + inset: x + w - inset]
                if cell.size == 0 or min(cell.shape[:2]) < 4:
                    line.cells.append(GetsCell(day=day, hours=None, status="EMPTY"))
                    continue
                fill, mask, bbox = _glyphs(cell)
                if bbox is None:
                    line.cells.append(GetsCell(day=day, hours=None, status="EMPTY"))
                    continue
                status = "FILLED" if self.monochrome else _classify_fill(fill)
                gc = GetsCell(day=day, hours=None, status=status if status != "EMPTY" else "FILLED")
                line.cells.append(gc)
                pending.append((line, gc, _clean_crop(cell, fill, mask, bbox)))

        results = self.ocr.recognize([c for _, _, c in pending])
        for (line, gc, crop), (text, score) in zip(pending, results, strict=True):
            value = parse_number(text)
            if value is None or not (0 < float(value) <= 24):
                alt = _tesseract_number(crop)
                if alt is not None and 0 < float(alt) <= 24:
                    value, score = alt, min(score, 0.8)
                else:
                    value = None
            gc.raw = text.strip()
            gc.hours = value
            gc.confidence = round(float(score), 3) if value is not None else 0.0
            if value is None:
                line.issues.append(f"day {gc.day}: unreadable value {text!r}")
            elif score < 0.85:
                line.issues.append(f"day {gc.day}: low-confidence read {text!r} ({score:.2f})")
            line.confidence = min(line.confidence, gc.confidence)

    # ---- Total column + totals rows -----------------------------------------------

    def _total_column_span(self) -> tuple[int, int]:
        g = self.grid
        x0 = g.cols[-1][1] + 2
        x1 = g.table[2] - 1 if g.table[2] > x0 + 10 else int(x0 + 1.6 * g.pitch)
        return x0, min(x1, int(x0 + 2.5 * g.pitch), self.rgb.shape[1])

    def _read_numbers(self, regions: list[tuple[float, float, int, int]]):
        """Reads one number per (y0, y1, x0, x1) region in a single batched
        recognition call; (None, 0.0) where a region holds no glyphs."""
        crops, idx = [], []
        for i, (y0, y1, xa, xb) in enumerate(regions):
            region = self.rgb[max(0, int(y0) + 1): int(y1), max(0, xa): xb]
            if region.size == 0 or min(region.shape[:2]) < 4:
                continue
            fill, mask, bbox = _glyphs(region, min_height_frac=0.2)
            if bbox is None:
                continue
            crops.append(_clean_crop(region, fill, mask, bbox))
            idx.append(i)
        out: list[tuple[float | None, float]] = [(None, 0.0)] * len(regions)
        for k, (text, score) in enumerate(self.ocr.recognize(crops)):
            value = parse_number(text)
            if value is None:
                alt = _tesseract_number(crops[k])
                if alt is not None:
                    value, score = alt, min(score, 0.8)
            out[idx[k]] = (value, score)
        return out

    def _read_total_column(self) -> None:
        g = self.grid
        tx0, tx1 = self._total_column_span()
        if tx1 - tx0 < 8:
            self.sheet.warnings.append("Total column not visible")
            return
        regions = [(y0 - 2, y1 + 2, tx0, tx1) for y0, y1 in g.rows]
        half = g.pitch / 2
        spans = [(int((a + b) / 2 - half + 1), int((a + b) / 2 + half - 1)) for a, b in g.cols]
        spans.append((tx0, tx1))
        bands = [(band, label) for band, label in zip(self.totals_bands, self.totals_labels, strict=True)
                 if label]
        seen: set[str] = set()
        bands = [(b, lab) for b, lab in bands if not (lab in seen or seen.add(lab))]
        for (by0, by1), _label in bands:
            regions.extend((by0, by1, xa, xb) for xa, xb in spans)
        values = self._read_numbers(regions)

        for line, (value, score) in zip(self.lines, values[: len(self.lines)], strict=True):
            line.printed_total = value
            if value is None:
                line.issues.append("row total unreadable")
            elif score < 0.85:
                line.confidence = min(line.confidence, score)
        pos = len(self.lines)
        for _band, label in bands:
            chunk = values[pos: pos + len(spans)]
            pos += len(spans)
            self.sheet.totals[label] = [v for v, _ in chunk[:-1]]
            self.sheet.totals_printed_total[label] = chunk[-1][0]

    # ---- page header: employee name, month, year -----------------------------

    def _read_page_header(self) -> None:
        g = self.grid
        top = g.table[1]
        if top < 20:
            self.sheet.warnings.append("page header (employee name, month) not in the screenshot")
            return
        region = self.rgb[:top]
        self._read_period_dropdowns(region)
        # the greeting sits in the left ~60 % of the page, above the buttons
        tokens = self.ocr.detect(region[:, : int(region.shape[1] * 0.62)])
        for tok in tokens:
            _restore_spaces(tok, self.gray)
        name = ""
        for tok in tokens:
            m = _GREETING.search(tok["text"])
            if m:
                name = m.group(1)
                break
            if _GREETING_ONLY.fullmatch(tok["text"].strip()):
                same = sorted(
                    (t for t in tokens if abs(t["yc"] - tok["yc"]) < 0.5 * (tok["y1"] - tok["y0"])
                     and t["x0"] > tok["x1"] - 2),
                    key=lambda t: t["x0"],
                )
                name = " ".join(t["text"] for t in same)
                break
        self.sheet.employee_name = _clean_name(name)
        letters = [c for c in self.sheet.employee_name if c.isalpha()]
        gets_style = re.search(r"\([A-Za-z]\.?\)$", self.sheet.employee_name)
        if letters and (gets_style or sum(c.isupper() for c in letters) >= 0.6 * len(letters)):
            # GETS prints names in capitals; recognisers slip on case alone
            self.sheet.employee_name = self.sheet.employee_name.upper()
        if self.sheet.month is None or self.sheet.year is None:
            self._period_from_text(" ".join(t["text"] for t in tokens))

    def _read_period_dropdowns(self, region: np.ndarray) -> None:
        """Year / month live in blue dropdowns just above the grid's right side."""
        hsv = cv2.cvtColor(region, cv2.COLOR_RGB2HSV)
        blue = ((hsv[..., 0] >= 100) & (hsv[..., 0] <= 130) & (hsv[..., 1] > 110) & (hsv[..., 2] > 80))
        n, _labels, stats, _ = cv2.connectedComponentsWithStats(blue.astype(np.uint8), connectivity=8)
        bh = self.grid.box_h
        crops = []
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if 0.8 * bh <= h <= 2.5 * bh and 1.2 * h <= w <= 8 * h and area > 0.5 * w * h:
                if x > self.grid.cols[0][0]:           # right-hand controls only
                    crop = region[y + 2:y + h - 2, x + 3:x + w - 3]
                    crops.append(crop)
                    # without the dropdown chevron (it can swamp short words)
                    crops.append(crop[:, : max(8, int(crop.shape[1] * 0.72))])
        texts = [t for t, s in self.ocr.recognize(crops) if s > 0.5]
        self._period_from_text(" ".join(texts))

    def _period_from_text(self, text: str) -> None:
        for word in re.findall(r"[A-Za-z]{3,}|\d{4}", text or ""):
            if re.fullmatch(r"20\d{2}", word):
                if self.sheet.year is None:
                    self.sheet.year = int(word)
                continue
            lw = word.lower()
            if self.sheet.month is None and len(lw) >= 3:
                if lw in MONTHS:
                    self.sheet.month = MONTHS[lw]
                elif len(lw) >= 4:
                    best = max(MONTHS, key=lambda m: _fuzzy(m, lw))
                    if _fuzzy(best, lw) >= 0.8:
                        self.sheet.month = MONTHS[best]

    # ---- identity + reconciliation -------------------------------------------------

    def _fill_sheet_identity(self) -> None:
        def majority(values):
            vals = [v for v in values if v]
            return max(set(vals), key=vals.count) if vals else ""

        s = self.sheet
        s.person_id = majority([ln.person_id for ln in self.lines])
        s.supplier = majority([ln.supplier for ln in self.lines])
        s.job_family = majority([ln.job_family for ln in self.lines])
        for ln in self.lines:
            if s.person_id and ln.person_id != s.person_id:
                if ln.person_id:
                    s.corrections.append(
                        f"row {ln.row_index + 1}: person id {ln.person_id!r} → {s.person_id!r} (sheet majority)"
                    )
                ln.person_id = s.person_id
                ln.issues = [i for i in ln.issues if i != "person id unreadable"]
            for attr in ("supplier", "job_family"):
                val, maj = getattr(ln, attr), getattr(s, attr)
                if maj and val != maj and (not val or _fuzzy(_norm(val), _norm(maj)) >= 0.75):
                    setattr(ln, attr, maj)

        # the weekday header tells us the calendar even without the dropdowns
        if s.weekdays and (s.year is None or s.month is None):
            self._infer_period_from_weekdays()
        if s.year and s.month:
            expected = calendar.monthrange(s.year, s.month)[1]
            if expected != s.days_in_month:
                s.warnings.append(
                    f"{calendar.month_name[s.month]} {s.year} has {expected} days "
                    f"but the grid shows {s.days_in_month}"
                )
            if s.weekdays and not self._weekdays_match(s.year, s.month):
                s.warnings.append("weekday header does not match the selected month/year")
            else:
                # complete the (sampled) weekday row from the calendar
                s.weekdays = [
                    WEEKDAYS[calendar.weekday(s.year, s.month, d)]
                    for d in range(1 + self.day_offset, expected + 1)
                ][: s.days_in_month]
        else:
            s.warnings.append("month/year not readable from the screenshot")

    def _weekdays_match(self, year: int, month: int) -> bool:
        first = calendar.weekday(year, month, 1 + self.day_offset)
        read = [(i, w) for i, w in enumerate(self.sheet.weekdays) if w]
        agree = sum(1 for i, w in read if w == WEEKDAYS[(first + i) % 7])
        return agree >= max(3, int(0.6 * len(read)))

    def _infer_period_from_weekdays(self) -> None:
        from datetime import date

        s = self.sheet
        today = date.today()
        candidates = []
        for delta in range(-18, 7):
            m0 = today.month - 1 + delta
            y, m = today.year + m0 // 12, m0 % 12 + 1
            if s.year and y != s.year:
                continue
            if s.month and m != s.month:
                continue
            if calendar.monthrange(y, m)[1] != s.days_in_month:
                continue
            if self._weekdays_match(y, m):
                candidates.append((abs(delta), y, m))
        if len(candidates) == 1:
            _, y, m = candidates[0]
            s.year, s.month = s.year or y, s.month or m
            s.warnings.append(f"month/year inferred from the weekday header ({calendar.month_name[m]} {y})")
        elif candidates:
            names = ", ".join(f"{calendar.month_name[m]} {y}" for _, y, m in sorted(candidates))
            s.warnings.append(f"month/year unreadable; the weekday header fits several months ({names})")

    def _reconcile(self) -> None:
        s, lines = self.sheet, self.lines

        def members(label: str) -> list[GetsLine]:
            return lines if label == "TOTAL" else [ln for ln in lines if ln.uom == label]

        def set_cell(c: GetsCell, val: float, why: str) -> None:
            old = c.hours
            c.hours = int(val) if float(val).is_integer() else val
            c.corrected = True
            c.confidence = max(c.confidence, 0.9)
            s.corrections.append(f"{why}: {_fmt(old) or '∅'} → {_fmt(val)}")

        # 0) unreadable hour types: the per-type day totals decide them when
        #    exactly one assignment makes every day add up
        types = [k for k in s.totals if k != "TOTAL"]
        unknown = [ln for ln in lines if ln.uom not in types]
        if unknown and len(types) >= 2 and len(unknown) <= 4:
            fits = [combo for combo in itertools.product(types, repeat=len(unknown))
                    if self._uoms_fit(unknown, combo, types)]
            if len(fits) == 1:
                for ln, uom in zip(unknown, fits[0], strict=True):
                    s.corrections.append(
                        f"row {ln.row_index + 1}: hour type {ln.uom or '∅'} → {uom} (day totals)"
                    )
                    ln.uom = uom

        # 1) one unknown in a row: the printed row total determines it
        for ln in lines:
            unknown = [c for c in ln.cells if c.status != "EMPTY" and c.hours is None]
            if len(unknown) == 1 and ln.printed_total is not None:
                rest = sum(c.hours for c in ln.cells if c.hours is not None)
                val = round(ln.printed_total - rest, 2)
                if 0 < val <= 24:
                    set_cell(unknown[0], val, f"row {ln.row_index + 1} day {unknown[0].day} (row total)")

        # 2) per-day constraints from the totals rows
        for label, day_totals in s.totals.items():
            group = members(label)
            if not group:
                continue
            for di, expected in enumerate(day_totals):
                if expected is None:
                    continue
                day = di + 1 + self.day_offset
                cells = [(ln, c) for ln in group for c in ln.cells if c.day == day]
                got = sum(c.hours or 0 for _, c in cells)
                if abs(got - expected) < 1e-6:
                    continue
                inked = [(ln, c) for ln, c in cells if c.status != "EMPTY"]
                suspects = [(ln, c) for ln, c in inked if c.hours is None or c.confidence < 0.9]
                if not suspects and len(inked) == 1:
                    # a single read disagrees with the day total: trust it only
                    # if the row total agrees with the corrected value
                    ln, c = inked[0]
                    val = round(expected, 2)
                    if ln.printed_total is not None and abs(
                        ln.computed_total - (c.hours or 0) + val - ln.printed_total
                    ) < 1e-6:
                        suspects = inked
                if len(suspects) == 1:
                    ln, c = suspects[0]
                    others = sum(x.hours or 0 for _, x in cells if x is not c)
                    val = round(expected - others, 2)
                    if 0 < val <= 24:
                        set_cell(c, val, f"row {ln.row_index + 1} day {day} ({label} day total {_fmt(expected)})")

        # 3) verification (after repairs)
        checks: list[dict] = []
        for ln in lines:
            if ln.printed_total is None:
                checks.append({"check": f"row {ln.row_index + 1} total readable", "ok": False,
                               "expected": "number", "actual": None})
                continue
            ok = abs(ln.computed_total - ln.printed_total) < 1e-6
            checks.append({
                "check": f"row {ln.row_index + 1} ({ln.sub_project or ln.project_id}) sum",
                "expected": ln.printed_total, "actual": ln.computed_total, "ok": ok,
            })
            if not ok:
                ln.issues.append(
                    f"row sum {_fmt(ln.computed_total)} ≠ printed total {_fmt(ln.printed_total)}"
                )
        for label, day_totals in s.totals.items():
            group = members(label)
            if not group and label != "TOTAL":
                # a totals row for an hour type with no lines must be all zero
                nonzero = [i + 1 for i, v in enumerate(day_totals) if v]
                checks.append({"check": f"{label} day totals", "expected": 0,
                               "actual": len(nonzero), "ok": not nonzero, "mismatched_days": nonzero})
                continue
            mismatched = []
            for di, expected in enumerate(day_totals):
                if expected is None:
                    continue
                day = di + 1 + self.day_offset
                got = sum((c.hours or 0) for ln in group for c in ln.cells if c.day == day)
                if abs(got - expected) > 1e-6:
                    mismatched.append(day)
            readable = sum(1 for v in day_totals if v is not None)
            checks.append({
                "check": f"{label} day totals",
                "expected": len(day_totals), "actual": readable - len(mismatched),
                "ok": not mismatched and readable >= 0.9 * len(day_totals),
                "mismatched_days": mismatched,
            })
            printed = s.totals_printed_total.get(label)
            got = round(sum((c.hours or 0) for ln in group for c in ln.cells), 2)
            checks.append({
                "check": f"{label} grand total", "expected": printed, "actual": got,
                "ok": printed is not None and abs(got - printed) < 1e-6,
            })
        if not s.totals:
            s.warnings.append("totals rows not found — values could not be cross-checked")
            checks.append({"check": "totals rows present", "expected": "NC/STD/Total rows",
                           "actual": None, "ok": False})
        if not (s.year and s.month):
            checks.append({"check": "month and year readable", "expected": "period",
                           "actual": None, "ok": False})
        unread = [(ln.row_index + 1, c.day) for ln in lines for c in ln.cells
                  if c.status != "EMPTY" and c.hours is None]
        if unread:
            checks.append({"check": "all filled cells readable", "expected": 0,
                           "actual": len(unread), "ok": False})
        s.checks = checks


    def _uoms_fit(self, unknown: list[GetsLine], combo: tuple[str, ...], types: list[str]) -> bool:
        original = [ln.uom for ln in unknown]
        for ln, uom in zip(unknown, combo, strict=True):
            ln.uom = uom
        try:
            for uom in types:
                group = [ln for ln in self.lines if ln.uom == uom]
                for di, expected in enumerate(self.sheet.totals.get(uom, [])):
                    if expected is None:
                        continue
                    day = di + 1 + self.day_offset
                    got = sum((c.hours or 0) for ln in group for c in ln.cells if c.day == day)
                    if abs(got - expected) > 1e-6:
                        return False
            return True
        finally:
            for ln, uom in zip(unknown, original, strict=True):
                ln.uom = uom


def _clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", (name or "")).strip(" ,.;:")
    name = re.sub(r"\s*,\s*", ", ", name)
    name = re.sub(r"\s*\(\s*", " (", name)
    name = re.sub(r"\s*\)", ")", name)
    return name.strip()


def _tesseract_number(crop: np.ndarray) -> float | None:
    """Second opinion for a numeric crop (optional dependency)."""
    try:
        import pytesseract
    except ImportError:  # pragma: no cover - optional
        return None
    if crop.size == 0 or min(crop.shape[:2]) < 4:
        return None
    _fill, mask, bbox = _glyphs(crop, min_height_frac=0.15)
    if bbox is None:
        return None
    img = np.where(mask, 0, 255).astype(np.uint8)
    big = cv2.resize(img, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
    big = cv2.copyMakeBorder(big, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    try:
        text = pytesseract.image_to_string(
            big, config="--psm 7 -c tessedit_char_whitelist=0123456789."
        ).strip()
    except Exception:  # noqa: BLE001 — binary missing/crash: no second opinion
        return None
    return parse_number(text)
