"""OCR accuracy regression, the core promise of the product.

Synthetic sheets (invented data, 28-31 day months, several fonts and zoom levels) must match their
ground truth field-for-field and pass the sheet's own arithmetic checks. Degraded copies (rescale,
JPEG, blur, noise) must keep every hour, total, status, person id and period exact; free-text labels
may carry small OCR slips, which never affect the leave rule.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("rapidocr_onnxruntime")

from scripts.eval_ocr_accuracy import score, variants  # noqa: E402
from scripts.gen_synthetic_timesheets import ensure  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SYN_DIR = ensure()
if SYN_DIR is None:
    pytest.skip("synthetic timesheets need Playwright + Chromium", allow_module_level=True)
SYNTHETIC = json.loads((SYN_DIR / "ground_truth.json").read_text())

VARIANTS = ["original", "scale0.8", "scale1.25", "scale1.5", "scale2.0", "jpeg60", "blur", "noise"]
DEGRADED_SAMPLES = ["synthetic_000.png", "synthetic_002.png", "synthetic_007.png", "synthetic_010.png"]
TEXT_LABELS = ("employee_name", "supplier", "job_family", ".sub_project:")


def _load(directory: Path, name: str, which: str = "original") -> np.ndarray:
    img = Image.open(directory / name).convert("RGB")
    return np.asarray(dict(variants(img))[which])


@pytest.mark.parametrize("name", sorted(SYNTHETIC))
def test_synthetic_sheet_exact(name):
    from app.services.extraction.timesheet_grid import read_timesheet

    sheet = read_timesheet(_load(SYN_DIR, name))
    errors = score(sheet, SYNTHETIC[name])
    assert not errors, "\n".join(errors)
    assert sheet.status in ("VERIFIED", "CORRECTED")


@pytest.mark.parametrize("which", VARIANTS[1:])
@pytest.mark.parametrize("name", DEGRADED_SAMPLES)
def test_synthetic_sheet_exact_under_capture_conditions(name, which):
    from app.services.extraction.timesheet_grid import read_timesheet

    sheet = read_timesheet(_load(SYN_DIR, name, which))
    errors = [e for e in score(sheet, SYNTHETIC[name]) if not any(t in e for t in TEXT_LABELS)]
    assert not errors, "\n".join(errors)
    assert sheet.status in ("VERIFIED", "CORRECTED")


def test_layout_probe_accepts_timesheet_and_rejects_other_images():
    from app.services.extraction.timesheet_grid import is_timesheet_screenshot

    assert is_timesheet_screenshot(_load(SYN_DIR, "synthetic_000.png"))
    blank = np.full((600, 1200, 3), 255, np.uint8)
    assert not is_timesheet_screenshot(blank)
    rng = np.random.default_rng(1)
    assert not is_timesheet_screenshot(rng.integers(0, 255, (500, 900, 3), dtype=np.uint8))


def test_non_timesheet_image_raises_layout_error():
    from app.services.extraction.timesheet_grid import SheetLayoutError, read_timesheet

    with pytest.raises(SheetLayoutError):
        read_timesheet(np.full((400, 800, 3), 240, np.uint8))


def test_sheet_serialises_with_verification_report():
    from app.services.extraction.timesheet_grid import read_timesheet

    data = read_timesheet(_load(SYN_DIR, "synthetic_007.png")).to_dict()
    json.dumps(data)
    assert data["period"] == "2025-07"
    assert data["verified"] is True
    ooo = [ln for ln in data["lines"] if ln["is_out_of_office"]]
    assert len(ooo) == 1 and ooo[0]["computed_total"] == 32
    assert len(data["weekdays"]) == 31 and data["weekdays"][0] == "Tu"
