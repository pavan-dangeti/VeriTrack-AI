"""OCR accuracy regression, the core promise of the product.

Synthetic sheets (invented data, 28-31 day months, several fonts and zoom levels) must match their
ground truth field-for-field and pass the sheet's own arithmetic checks. Degraded copies (rescale,
JPEG, blur, noise) must keep every hour, total, status, person id and period exact; free-text labels
may carry small OCR slips, which never affect the leave rule.

Private sheets are never committed: put them with a ground_truth.json in private-data/gets (or set
GETS_PRIVATE_DIR) and the same checks run on them.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("rapidocr_onnxruntime")

from scripts.eval_gets_accuracy import score, variants  # noqa: E402
from scripts.gen_synthetic_gets import ensure  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SYN_DIR = ensure()
if SYN_DIR is None:
    pytest.skip("synthetic GETS sheets need Playwright + Chromium", allow_module_level=True)
SYNTHETIC = json.loads((SYN_DIR / "ground_truth.json").read_text())
PRIVATE_DIR = Path(os.environ.get("GETS_PRIVATE_DIR", ROOT / "private-data/gets"))
PRIVATE = (
    json.loads((PRIVATE_DIR / "ground_truth.json").read_text())
    if (PRIVATE_DIR / "ground_truth.json").exists()
    else {}
)

VARIANTS = ["original", "scale0.8", "scale1.25", "scale1.5", "scale2.0", "jpeg60", "blur", "noise"]
DEGRADED_SAMPLES = ["synthetic_000.png", "synthetic_002.png", "synthetic_007.png", "synthetic_010.png"]
TEXT_LABELS = ("employee_name", "supplier", "job_family", ".sub_project:")


def _load(directory: Path, name: str, which: str = "original") -> np.ndarray:
    img = Image.open(directory / name).convert("RGB")
    return np.asarray(dict(variants(img))[which])


@pytest.mark.parametrize("name", sorted(SYNTHETIC))
def test_synthetic_sheet_exact(name):
    from app.services.extraction.gets_grid import read_gets_sheet

    sheet = read_gets_sheet(_load(SYN_DIR, name))
    errors = score(sheet, SYNTHETIC[name])
    assert not errors, "\n".join(errors)
    assert sheet.status in ("VERIFIED", "CORRECTED")


@pytest.mark.parametrize("which", VARIANTS[1:])
@pytest.mark.parametrize("name", DEGRADED_SAMPLES)
def test_synthetic_sheet_exact_under_capture_conditions(name, which):
    from app.services.extraction.gets_grid import read_gets_sheet

    sheet = read_gets_sheet(_load(SYN_DIR, name, which))
    errors = [e for e in score(sheet, SYNTHETIC[name]) if not any(t in e for t in TEXT_LABELS)]
    assert not errors, "\n".join(errors)
    assert sheet.status in ("VERIFIED", "CORRECTED")


@pytest.mark.skipif(not PRIVATE, reason="no private GETS sheets (private-data/gets)")
@pytest.mark.parametrize("which", VARIANTS)
@pytest.mark.parametrize("name", sorted(PRIVATE))
def test_private_real_sheet_exact(name, which):
    from app.services.extraction.gets_grid import read_gets_sheet

    sheet = read_gets_sheet(_load(PRIVATE_DIR, name, which))
    errors = score(sheet, PRIVATE[name])
    assert not errors, "\n".join(errors)
    assert sheet.status in ("VERIFIED", "CORRECTED")
    assert sheet.confidence >= 0.9


def test_layout_probe_accepts_gets_and_rejects_other_images():
    from app.services.extraction.gets_grid import is_gets_screenshot

    assert is_gets_screenshot(_load(SYN_DIR, "synthetic_000.png"))
    blank = np.full((600, 1200, 3), 255, np.uint8)
    assert not is_gets_screenshot(blank)
    rng = np.random.default_rng(1)
    assert not is_gets_screenshot(rng.integers(0, 255, (500, 900, 3), dtype=np.uint8))


def test_non_gets_image_raises_layout_error():
    from app.services.extraction.gets_grid import GetsLayoutError, read_gets_sheet

    with pytest.raises(GetsLayoutError):
        read_gets_sheet(np.full((400, 800, 3), 240, np.uint8))


def test_sheet_serialises_with_verification_report():
    from app.services.extraction.gets_grid import read_gets_sheet

    data = read_gets_sheet(_load(SYN_DIR, "synthetic_007.png")).to_dict()
    json.dumps(data)
    assert data["period"] == "2025-07"
    assert data["verified"] is True
    ooo = [ln for ln in data["lines"] if ln["is_out_of_office"]]
    assert len(ooo) == 1 and ooo[0]["computed_total"] == 32
    assert len(data["weekdays"]) == 31 and data["weekdays"][0] == "Tu"
