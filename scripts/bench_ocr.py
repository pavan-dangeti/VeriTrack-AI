"""OCR benchmark at realistic scale: generated timesheets, each with one controlled degradation.

    python -m scripts.bench_ocr generate --out bench-data [--count 220] [--seed 7]
    python -m scripts.bench_ocr generate --out bench-heldout --seed 4729   # held-out set, see HELDOUT_SEED
    python -m scripts.bench_ocr run --data bench-data --out bench-out [--engine rapid|tesseract]
                                    [--preprocess] [--shard 1/4]
    python -m scripts.bench_ocr report bench-out [more result dirs ...] > report.md
    python -m scripts.bench_ocr print --out print-set      # 20 numbered sheets to print and photograph

The sheets are rendered with the same generator as the regression tests, made more realistic (decimal
hours, notes, longer task names, up to nine rows), then degraded: blur, skew, noise, JPEG artefacts,
shadows, low resolution, stamps, pen marks and handwritten corrections, plus simulated phone photos
(perspective tilt, page curl, uneven lighting with a colour cast, camera noise, defocus and JPEG). No real
photographs are used: the simulated photos are an approximation, not evidence of photo support.
Everything is synthetic and written to git-ignored folders.

Fields are split by what the product acts on:
  checked    hours, row and sheet totals, number of rows, person ID, period, hour type and each row's leave
             flag (whether its task is 'Out Of Office'); the leave check depends on every one of them
  unchecked  employee name, client, role, task title, project and task codes: shown and exported, but no
             total covers them and the leave check does not use them

Outcomes per sheet:
  exact                    verified, and every checked and unchecked field matches the ground truth
  verified_unchecked_slip  verified, every checked field right, but an unchecked field differs
  flagged                  the reader marked the sheet NEEDS_REVIEW, or refused it as not a timesheet
  verified_wrong           verified while a checked field is wrong: the outcome that must never happen
  error                    the reader crashed
A handwritten correction changes a value on paper that the printed totals still agree with, so for those
sheets the only safe outcome is 'flagged'; verifying them counts as verified_wrong.
"""

from __future__ import annotations

import argparse
import io
import json
import platform
import random
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Development set: seed 7, used while fixing the reader. Held-out set: seed 4729, fixed on 2026-10-13 before
# any of its sheets were generated, and only read once the fixes were final. Same generator and degradations,
# so it shows whether the fixes overfit the development sheets, not how the reader handles other kinds of input.
DEV_SEED = 7
HELDOUT_SEED = 4729

DEGRADATIONS = ("clean", "blur", "skew", "noise", "jpeg", "shadow", "lowres", "stamp", "pen", "correction",
                "simulated_photo")
SEVERITIES = ("low", "medium", "high")
PARAMS = {  # per severity
    "blur": {"low": 0.6, "medium": 1.0, "high": 1.4},          # Gaussian sigma (px)
    "skew": {"low": 0.8, "medium": 1.8, "high": 3.0},          # rotation (degrees)
    "noise": {"low": 6, "medium": 12, "high": 20},             # Gaussian noise std (grey levels)
    "jpeg": {"low": 60, "medium": 40, "high": 25},             # JPEG quality
    "shadow": {"low": 0.75, "medium": 0.6, "high": 0.45},      # darkest relative brightness
    "lowres": {"low": 0.7, "medium": 0.55, "high": 0.45},      # downscale factor
    "stamp": {"low": 0.3, "medium": 0.45, "high": 0.6},        # stamp opacity
    "pen": {"low": 2, "medium": 5, "high": 9},                 # number of pen marks
    "correction": {"low": 1, "medium": 1, "high": 2},          # struck-through cells
    "simulated_photo": {                                        # camera held roughly over a printed page
        "low": {"tilt": 0.02, "curl": 0.004, "darkest": 0.8, "noise": 4, "blur": 0.5, "jpeg": 85},
        "medium": {"tilt": 0.04, "curl": 0.009, "darkest": 0.65, "noise": 7, "blur": 0.8, "jpeg": 75},
        "high": {"tilt": 0.07, "curl": 0.015, "darkest": 0.5, "noise": 10, "blur": 1.1, "jpeg": 65},
    },
}
BENCH_TASKS = ["Onboarding flow", "Billing API", "Data Pipeline", "Release_24", "Search_v2", "Payments",
               "Mobile App", "Design System", "QA", "Infra_Core", "Analytics", "Docs_Hub", "Support",
               "Migration", "Customer Portal", "Reporting", "Security review", "Platform upgrade"]
NOTES = ["WFH", "on-site", "Release prep", "Client visit", "Sprint 42", "Training", "Hotfix"]
PEN_INK = [(25, 45, 160), (30, 30, 35), (20, 70, 150)]


# ---- sheets ------------------------------------------------------------------------------------------

def make_bench_sheet(rng: random.Random) -> dict:
    """A regression-style sheet with more realism. Totals are recomputed after every change."""
    from scripts.gen_synthetic_timesheets import make_sheet

    sheet = make_sheet(rng)
    for ln in sheet["lines"]:
        if ln["sub_project"] != "Out Of Office":
            ln["sub_project"] = rng.choice(BENCH_TASKS)
            for d in list(ln["days"]):
                if rng.random() < 0.12:
                    ln["days"][d] = rng.choice([7.5, 4.5, 6.5, 3.5])
        if rng.random() < 0.25:
            ln["notes"] = rng.choice(NOTES)
        ln["total"] = _num(sum(ln["days"].values()))
    for kind in ("REG", "NB"):
        sheet["totals"][kind] = _num(sum(ln["total"] for ln in sheet["lines"] if ln["uom"] == kind))
    sheet["totals"]["TOTAL"] = _num(sheet["totals"]["REG"] + sheet["totals"]["NB"])
    return sheet


def _num(v: float) -> float | int:
    return int(v) if float(v).is_integer() else round(v, 2)


GEOMETRY_JS = """() => {
    const rect = el => (r => [r.left, r.top, r.right, r.bottom])(el.getBoundingClientRect());
    return {
        table: rect(document.querySelector('table')),
        rows: [...document.querySelectorAll('table tr')].slice(1)
              .map(tr => [...tr.querySelectorAll('.box')].map(rect)).filter(r => r.length),
    };
}"""


def _render(browser, html: str, zoom: float, attempts: int = 3):
    """Screenshot plus day-box geometry. Headless Chromium occasionally fails a capture ('Unable to capture
    screenshot'); the sheet is rendered again on a fresh page rather than failing the whole benchmark."""
    for attempt in range(attempts):
        page = browser.new_page(viewport={"width": 1900, "height": 800}, device_scale_factor=zoom)
        try:
            page.set_content(html)
            return page.evaluate(GEOMETRY_JS), page.screenshot(full_page=True)
        except Exception:
            if attempt == attempts - 1:
                raise
        finally:
            page.close()
    raise AssertionError("unreachable")


def generate(out: Path, count: int, seed: int) -> None:
    import os

    from playwright.sync_api import sync_playwright

    from scripts.gen_synthetic_timesheets import FONTS, render_html

    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)  # noqa: S311 — benchmark data, not crypto
    plan = [(DEGRADATIONS[i % len(DEGRADATIONS)], SEVERITIES[(i // len(DEGRADATIONS)) % 3]) for i in range(count)]
    truth = {}
    with sync_playwright() as p:
        exe = os.environ.get("CHROMIUM_PATH")
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        for i, (kind, severity) in enumerate(plan):
            sheet = make_bench_sheet(rng)
            zoom = rng.choice([0.8, 0.9, 1.0, 1.0, 1.1, 1.25, 1.5])
            geometry, png = _render(browser, render_html(sheet, FONTS[i % len(FONTS)]), zoom)
            img = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))
            geo = {"table": [v * zoom for v in geometry["table"]],
                   "rows": [[[v * zoom for v in box] for box in row] for row in geometry["rows"]]}
            drng = random.Random(seed * 100_003 + i)  # noqa: S311
            degraded, params, edits = degrade(img, kind, severity, geo, sheet, drng)
            name = f"{i:03d}_{kind}_{severity}.png"
            Image.fromarray(degraded).save(out / name)
            truth[name] = {**sheet, "degradation": {"type": kind, "severity": severity, "params": params,
                                                    "zoom": zoom, "edits": edits},
                           "expected": "flagged" if kind == "correction" else "exact"}
        browser.close()
    (out / "truth.json").write_text(json.dumps(truth, indent=1))
    (out / "set.json").write_text(json.dumps({"seed": seed, "count": count,
                                              "set": "held-out" if seed == HELDOUT_SEED else "development"}))
    print(f"wrote {count} sheets to {out}")


def print_set(out: Path, count: int, seed: int) -> None:
    """One A4-landscape PDF page per sheet, each labelled VT-P-NN in the app bar, plus the ground truth."""
    import os

    from playwright.sync_api import sync_playwright
    from pypdf import PdfWriter

    from scripts.gen_synthetic_timesheets import FONTS, render_html

    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)  # noqa: S311 — benchmark data, not crypto
    writer, truth = PdfWriter(), {}
    with sync_playwright() as p:
        exe = os.environ.get("CHROMIUM_PATH")
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        for i in range(count):
            sid = f"VT-P-{i + 1:02d}"
            sheet = make_bench_sheet(rng)
            page = browser.new_page(viewport={"width": 1900, "height": 800})
            page.set_content(render_html(sheet, FONTS[i % len(FONTS)]))
            page.evaluate("""id => {
                const d = document.createElement('div');
                d.textContent = id;
                d.style.cssText = 'position:absolute;top:16px;right:160px;color:#fff;font:bold 22px sans-serif';
                document.body.appendChild(d);
            }""", sid)
            pdf = page.pdf(format="A4", landscape=True, print_background=True, scale=0.55, page_ranges="1",
                           margin={"top": "12mm", "bottom": "12mm", "left": "8mm", "right": "8mm"})
            page.close()
            writer.append(io.BytesIO(pdf))
            truth[sid] = sheet
        browser.close()
    with (out / "printable-timesheets.pdf").open("wb") as fh:
        writer.write(fh)
    (out / "truth.json").write_text(json.dumps(truth, indent=1))
    print(f"wrote {count} printable sheets to {out}")


# ---- degradations ------------------------------------------------------------------------------------

def degrade(img: np.ndarray, kind: str, severity: str, geo: dict, sheet: dict, rng: random.Random):
    p = PARAMS.get(kind, {}).get(severity)
    edits: list[dict] = []
    if kind == "clean":
        out = img
    elif kind == "blur":
        out = cv2.GaussianBlur(img, (0, 0), p)
    elif kind == "skew":
        p = p * rng.choice([-1, 1])
        out = _rotate(img, p)
    elif kind == "noise":
        out = _noise(img, p, rng)
    elif kind == "jpeg":
        out = _jpeg(img, p)
    elif kind == "shadow":
        out = _shadow(img, p, rng)
    elif kind == "lowres":
        out = cv2.resize(img, None, fx=p, fy=p, interpolation=cv2.INTER_AREA)
    elif kind == "stamp":
        out = _stamp(img, p, geo, rng)
    elif kind == "pen":
        out = _pen_marks(img, p, geo, rng)
    elif kind == "correction":
        out, edits = _corrections(img, p, geo, sheet, rng)
    elif kind == "simulated_photo":
        out = _simulated_photo(img, p, rng)
    else:
        raise ValueError(kind)
    return np.ascontiguousarray(out), p, edits


def _simulated_photo(img: np.ndarray, p: dict, rng: random.Random) -> np.ndarray:
    """A page photographed by hand: placed on a desk, seen at an angle, slightly curled, lit unevenly with a
    warm cast, then camera noise, a little defocus and JPEG. An approximation of a phone photo, not one."""
    h, w = img.shape[:2]
    margin = int(0.06 * max(h, w))
    desk = np.array([rng.randint(150, 175), rng.randint(135, 155), rng.randint(115, 135)], np.uint8)
    canvas = np.empty((h + 2 * margin, w + 2 * margin, 3), np.uint8)
    canvas[:] = desk
    # page curl: rows bend into a shallow arc across the page width
    amp = p["curl"] * h
    xs = np.arange(w, dtype=np.float32)
    map_y = (np.arange(h, dtype=np.float32)[:, None] - amp * np.sin(np.pi * xs / w)[None, :]).astype(np.float32)
    map_x = np.repeat(xs[None, :], h, 0)
    page = cv2.remap(img, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    canvas[margin:margin + h, margin:margin + w] = page
    # perspective tilt: each page corner moves inwards by up to `tilt` of the page size
    src = np.float32([[margin, margin], [margin + w, margin], [margin + w, margin + h], [margin, margin + h]])
    jitter = [[rng.uniform(0, p["tilt"]) * w * sx, rng.uniform(0, p["tilt"]) * h * sy]
              for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1))]
    dst = np.float32(src + np.float32(jitter))
    warped = cv2.warpPerspective(canvas, cv2.getPerspectiveTransform(src, dst), (canvas.shape[1], canvas.shape[0]),
                                 flags=cv2.INTER_LINEAR, borderValue=tuple(int(v) for v in desk))
    lit = _shadow(warped, p["darkest"], rng)
    cast = np.array([1.0, rng.uniform(0.95, 0.99), rng.uniform(0.86, 0.94)], np.float32)   # warm white balance
    lit = np.clip(lit.astype(np.float32) * cast, 0, 255).astype(np.uint8)
    noisy = _noise(cv2.GaussianBlur(lit, (0, 0), p["blur"]), p["noise"], rng)
    return _jpeg(noisy, p["jpeg"])


def _rotate(img: np.ndarray, angle: float) -> np.ndarray:
    return np.asarray(Image.fromarray(img).rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor="white"))


def _noise(img: np.ndarray, std: float, rng: random.Random) -> np.ndarray:
    gen = np.random.default_rng(rng.randrange(2**32))
    return np.clip(img.astype(np.int16) + gen.normal(0, std, img.shape), 0, 255).astype(np.uint8)


def _jpeg(img: np.ndarray, quality: int) -> np.ndarray:
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "JPEG", quality=quality)
    return np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"))


def _shadow(img: np.ndarray, darkest: float, rng: random.Random) -> np.ndarray:
    """Uneven lighting: a linear gradient in a random direction plus a soft dark blob."""
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    theta = rng.uniform(0, 2 * np.pi)
    lin = np.cos(theta) * xx / w + np.sin(theta) * yy / h
    lin = (lin - lin.min()) / max(1e-6, float(np.ptp(lin)))
    cx, cy, r = rng.uniform(0, w), rng.uniform(0, h), rng.uniform(0.25, 0.5) * max(h, w)
    blob = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r)))
    field = 1 - (1 - darkest) * np.clip(0.6 * lin + 0.6 * blob, 0, 1)
    return np.clip(img.astype(np.float32) * field[..., None], 0, 255).astype(np.uint8)


def _stamp(img: np.ndarray, opacity: float, geo: dict, rng: random.Random) -> np.ndarray:
    word = rng.choice(["APPROVED", "RECEIVED", "PAID", "CHECKED"])
    scale = max(1.0, (geo["table"][3] - geo["table"][1]) / 120)
    thick = max(2, int(2 * scale))
    (tw, th), _ = cv2.getTextSize(word, cv2.FONT_HERSHEY_DUPLEX, scale, thick)
    pad = int(0.4 * th)
    layer = np.zeros((th + 3 * pad, tw + 2 * pad, 3), np.uint8)
    cv2.rectangle(layer, (2, 2), (layer.shape[1] - 3, layer.shape[0] - 3), (210, 30, 40), thick)
    cv2.putText(layer, word, (pad, th + pad), cv2.FONT_HERSHEY_DUPLEX, scale, (210, 30, 40), thick)
    m = cv2.getRotationMatrix2D((layer.shape[1] / 2, layer.shape[0] / 2), rng.uniform(-18, 18), 1.0)
    layer = cv2.warpAffine(layer, m, (layer.shape[1], layer.shape[0]))
    x0, y0, x1, y1 = (int(v) for v in geo["table"])
    px = rng.randint(x0, max(x0, x1 - layer.shape[1]))
    py = rng.randint(max(0, y0 - layer.shape[0] // 3), max(0, y1 - layer.shape[0] // 2))
    out = img.copy()
    region = out[py:py + layer.shape[0], px:px + layer.shape[1]]
    ink = layer[: region.shape[0], : region.shape[1]]
    mask = ink.sum(2, keepdims=True) > 0
    region[:] = np.where(mask, (1 - opacity) * region + opacity * ink, region).astype(np.uint8)
    return out


def _pen_marks(img: np.ndarray, count: int, geo: dict, rng: random.Random) -> np.ndarray:
    """Ticks, circles, underlines and scribbled initials, some across day cells (not data)."""
    out = img.copy()
    boxes = [b for row in geo["rows"] for b in row]
    x0, y0, x1, y1 = (int(v) for v in geo["table"])
    unit = max(8, int(np.median([b[3] - b[1] for b in boxes]))) if boxes else 20
    for _ in range(count):
        ink = rng.choice(PEN_INK)
        t = max(1, unit // 10)
        kind = rng.choice(["tick", "circle", "underline", "initials"])
        if kind == "circle" and boxes:
            bx = rng.choice(boxes)
            c = (int((bx[0] + bx[2]) / 2), int((bx[1] + bx[3]) / 2))
            cv2.ellipse(out, c, (int(unit * 1.1), int(unit * 0.8)), rng.uniform(-20, 20), 20, 340, ink, t,
                        cv2.LINE_AA)
        elif kind == "tick":
            x, y = rng.randint(x0, x1), rng.randint(y0, y1)
            pts = np.array([[x, y], [x + unit // 3, y + unit // 2], [x + unit, y - unit // 2]], np.int32)
            cv2.polylines(out, [pts], False, ink, t, cv2.LINE_AA)
        elif kind == "underline":
            x, y = rng.randint(x0, max(x0, x1 - 6 * unit)), rng.randint(y0, y1)
            pts = np.array([[x + i * unit, y + rng.randint(-2, 2)] for i in range(6)], np.int32)
            cv2.polylines(out, [pts], False, ink, t, cv2.LINE_AA)
        else:
            x, y = rng.randint(x0, max(x0, x1 - 3 * unit)), rng.randint(y0 + unit, y1)
            cv2.putText(out, rng.choice(["ok", "AB", "jd", "chk"]), (x, y), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX,
                        unit / 22, ink, t, cv2.LINE_AA)
    return out


def _corrections(img: np.ndarray, count: int, geo: dict, sheet: dict, rng: random.Random):
    """Strikes through filled day cells and writes a different number beside them, as a person would."""
    out = img.copy()
    filled = [(ri, int(d)) for ri, ln in enumerate(sheet["lines"]) for d in ln["days"]
              if ri < len(geo["rows"]) and int(d) - 1 < len(geo["rows"][ri])]
    edits = []
    for ri, d in rng.sample(filled, min(count, len(filled))):
        bx0, by0, bx1, by1 = (int(v) for v in geo["rows"][ri][d - 1])
        ink = rng.choice(PEN_INK)
        t = max(2, (by1 - by0) // 8)
        cv2.line(out, (bx0 - 2, by1 - 2), (bx1 + 2, by0 + 2), ink, t, cv2.LINE_AA)
        printed = sheet["lines"][ri]["days"][str(d)]
        new = rng.choice([v for v in (2, 4, 6, 8) if v != printed])
        cv2.putText(out, str(new), (bx1 - (bx1 - bx0) // 3, by0 - 2), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX,
                    (by1 - by0) / 24, ink, t, cv2.LINE_AA)
        edits.append({"row": ri, "day": d, "printed": printed, "written": new})
    return out, edits


# ---- scoring -----------------------------------------------------------------------------------------

VERIFIED_MEANS = ("**Verified** means every day's hours agree with the printed row and sheet totals, the employee ID "
                  "and period were read, and every row's task was read clearly enough to tell leave from work. "
                  "Project and task codes, names, roles and task titles are not cross-checked.")

LINE_FIELDS = ("uom", "project_id", "sub_project", "sub_project_id")
UNCHECKED = {"employee_name", "supplier", "job_family", "sub_project", "project_id", "sub_project_id"}


def evaluate(sheet, truth: dict) -> dict:
    """Field-, cell- and sheet-level correctness of one read."""
    fields: dict[str, list[bool]] = defaultdict(list)
    fields["employee_name"].append(sheet.employee_name == truth["employee_name"])
    fields["person_id"].append(sheet.person_id == truth["person_id"])
    fields["period"].append((sheet.month, sheet.year) == (truth["month"], truth["year"]))
    fields["supplier"].append(sheet.supplier == truth["supplier"])
    fields["job_family"].append(sheet.job_family == truth["job_family"])
    cells, statuses = [], []
    for i, tl in enumerate(truth["lines"]):
        ln = sheet.lines[i] if i < len(sheet.lines) else None
        for key in LINE_FIELDS:
            fields[key].append(ln is not None and getattr(ln, key) == tl[key])
        fields["row_total"].append(ln is not None and ln.printed_total == tl["total"])
        fields["leave_flag"].append(ln is not None and ln.is_out_of_office == (tl["sub_project"] == "Out Of Office"))
        got = ln.hours_by_day if ln else {}
        for d in range(1, truth["days_in_month"] + 1):
            want = tl["days"].get(str(d))
            cells.append(got.get(d) == want)
            if want is not None and ln is not None:
                st = next((c.status for c in ln.cells if c.day == d), None)
                statuses.append(st == tl["status"])
    totals = [sheet.totals_printed_total.get(k) == v for k, v in truth["totals"].items()]
    line_count_ok = len(sheet.lines) == len(truth["lines"])
    numeric_ok = (all(cells) and all(totals) and line_count_ok
                  and all(all(v) for k, v in fields.items() if k not in UNCHECKED))
    return {"fields": {k: [sum(v), len(v)] for k, v in fields.items()},
            "cells": [sum(cells), len(cells)], "statuses": [sum(statuses), len(statuses)],
            "totals": [sum(totals), len(totals)], "line_count_ok": line_count_ok,
            "numeric_ok": numeric_ok, "exact": numeric_ok and all(all(v) for v in fields.values())}


def classify(status: str | None, ev: dict | None, expected: str) -> str:
    if status is None or ev is None:
        return "flagged"                      # refused as not a timesheet: safe, but not read
    verified = status in ("VERIFIED", "CORRECTED")
    if expected == "flagged":
        return "verified_wrong" if verified else "flagged"
    if not verified:
        return "flagged"
    if not ev["numeric_ok"]:
        return "verified_wrong"
    return "exact" if ev["exact"] else "verified_unchecked_slip"


# ---- run ---------------------------------------------------------------------------------------------

def run(data: Path, out: Path, engine: str, preprocess: bool, shard: str) -> None:
    from app.services.extraction.timesheet_grid import SheetLayoutError, read_timesheet
    from scripts.eval_ocr_accuracy import score

    truth = json.loads((data / "truth.json").read_text())
    k, n = (int(x) for x in shard.split("/"))
    names = [nm for i, nm in enumerate(sorted(truth)) if i % n == k - 1]
    out.mkdir(parents=True, exist_ok=True)
    (out / "failures").mkdir(exist_ok=True)
    set_file = data / "set.json"
    sheet_set = json.loads(set_file.read_text()) if set_file.exists() else {"set": "unknown", "seed": None}
    meta = {"engine": engine, "preprocess": preprocess, "machine": platform.machine(),
            "set": sheet_set["set"], "seed": sheet_set["seed"],
            "python": platform.python_version(), "commit": _commit(), "shard": shard,
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (out / f"meta-{k}.json").write_text(json.dumps(meta))
    with (out / f"results-{k}.jsonl").open("w") as fh:
        for nm in names:
            t = truth[nm]
            img = np.asarray(Image.open(data / nm).convert("RGB"))
            started = time.perf_counter()
            sheet, status, ev, warnings, error = None, None, None, [], None
            try:
                sheet = read_timesheet(img, engine=engine, **({"preprocess": True} if preprocess else {}))
                status, ev, warnings = sheet.status, evaluate(sheet, t), sheet.warnings
            except SheetLayoutError as exc:
                error = f"refused: {exc}"
            except Exception as exc:  # noqa: BLE001 — a crash is a result too
                error = f"{type(exc).__name__}: {exc}"[:300]
            refused = error is not None and error.startswith("refused")
            outcome = classify(status, ev, t["expected"]) if error is None or refused else "error"
            row = {"name": nm, "type": t["degradation"]["type"], "severity": t["degradation"]["severity"],
                   "expected": t["expected"], "status": status, "outcome": outcome,
                   "seconds": round(time.perf_counter() - started, 2), "eval": ev, "warnings": warnings[:5],
                   "error": error}
            fh.write(json.dumps(row) + "\n")
            if outcome != "exact":
                detail = {**row, "errors": score(sheet, t)[:8] if sheet is not None else []}
                (out / "failures" / f"{Path(nm).stem}.json").write_text(json.dumps(detail, indent=1))
            print(f"{outcome:18s} {nm} {row['seconds']}s", flush=True)


def _commit() -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
                                capture_output=True, text=True, cwd=ROOT, check=False)
        return result.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


# ---- report ------------------------------------------------------------------------------------------

def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "–"


def _agg(sel) -> dict:
    sel = list(sel)
    out = {"n": len(sel), "outcomes": defaultdict(int), "f": [0, 0], "c": [0, 0]}
    for r in sel:
        out["outcomes"][r["outcome"]] += 1
        if r["eval"]:
            for a, b in r["eval"]["fields"].values():
                out["f"][0] += a
                out["f"][1] += b
            out["c"][0] += r["eval"]["cells"][0]
            out["c"][1] += r["eval"]["cells"][1]
    return out


def report(dirs: list[Path]) -> str:
    rows, metas = [], []
    for d in dirs:
        for f in sorted(d.glob("results-*.jsonl")):
            rows += [json.loads(line) for line in f.read_text().splitlines() if line]
        metas += [json.loads(f.read_text()) for f in sorted(d.glob("meta-*.json"))]
    if not rows:
        return "no results\n"
    meta = metas[0]
    lines = ["The `simulated_photo` group is generated from screenshots; no real photographs were tested.", "",
             VERIFIED_MEANS, "",
             f"**{meta.get('set', 'unknown').capitalize()} set** (seed {meta.get('seed')}). "
             f"Engine **{meta['engine']}**, preprocessing **{'on' if meta['preprocess'] else 'off'}**, "
             f"`{meta['machine']}`, Python {meta['python']}, commit `{meta['commit']}`, {len(rows)} sheets.", "",
             "| Group | Sheets | Exact | Flagged | **Verified but wrong** | Verified, unchecked field wrong | Error | "
             "Field accuracy | Cell accuracy |", "|---|---|---|---|---|---|---|---|---|"]
    for label, sel in [("**All**", rows)] + [(t, [r for r in rows if r["type"] == t]) for t in DEGRADATIONS]:
        a = _agg(sel)
        if not a["n"]:
            continue
        o = a["outcomes"]
        lines.append(f"| {label} | {a['n']} | {o['exact']} ({_pct(o['exact'], a['n'])}) | {o['flagged']} | "
                     f"**{o['verified_wrong']}** | {o['verified_unchecked_slip']} | {o['error']} | "
                     f"{_pct(*a['f'])} | {_pct(*a['c'])} |")
    lines += ["", "By severity (exact / flagged / verified but wrong / verified with an unchecked field wrong, of n):",
              "",
              "| Degradation | Low | Medium | High |", "|---|---|---|---|"]
    for t in DEGRADATIONS:
        cells = []
        for s in SEVERITIES:
            a = _agg(r for r in rows if r["type"] == t and r["severity"] == s)
            o = a["outcomes"]
            cells.append(f"{o['exact']} / {o['flagged']} / {o['verified_wrong']} / {o['verified_unchecked_slip']} "
                         f"of {a['n']}" if a["n"] else "–")
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    field_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        for k, (a, b) in ((r["eval"] or {}).get("fields") or {}).items():
            field_totals[k][0] += a
            field_totals[k][1] += b
    lines += ["", "Per field, over every sheet that was read:", "", "| Field | Accuracy |", "|---|---|"]
    lines += [f"| {k} | {_pct(*v)} |" for k, v in field_totals.items()]
    secs = sorted(r["seconds"] for r in rows)
    lines += ["", f"Time per sheet: median {secs[len(secs) // 2]:.1f} s, slowest {secs[-1]:.1f} s.", ""]
    bad = [r for r in rows if r["outcome"] in ("verified_wrong", "error")]
    if bad:
        lines += ["Verified-but-wrong and errors (details in the run's failures/ folder):", ""]
        lines += [f"- `{r['name']}` — {r['outcome']} {r.get('error') or ''}".rstrip() for r in bad]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--out", type=Path, default=ROOT / "bench-data")
    g.add_argument("--count", type=int, default=220)
    g.add_argument("--seed", type=int, default=DEV_SEED)
    r = sub.add_parser("run")
    r.add_argument("--data", type=Path, default=ROOT / "bench-data")
    r.add_argument("--out", type=Path, default=ROOT / "bench-out")
    r.add_argument("--engine", choices=("rapid", "tesseract"), default="rapid")
    r.add_argument("--preprocess", action="store_true")
    r.add_argument("--shard", default="1/1")
    rep = sub.add_parser("report")
    rep.add_argument("dirs", nargs="+", type=Path)
    pr = sub.add_parser("print")
    pr.add_argument("--out", type=Path, default=ROOT / "print-set")
    pr.add_argument("--count", type=int, default=20)
    pr.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args(argv)
    if a.cmd == "generate":
        generate(a.out, a.count, a.seed)
    elif a.cmd == "run":
        run(a.data, a.out, a.engine, a.preprocess, a.shard)
    elif a.cmd == "print":
        print_set(a.out, a.count, a.seed)
    else:
        print(report(a.dirs), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
