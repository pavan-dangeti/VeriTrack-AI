"""Field-level accuracy of the GETS reader against ground truth.

    python -m scripts.eval_gets_accuracy [--variants] [--dir DIR]

DIR holds the images plus a ground_truth.json. It defaults to the synthetic
set in test-data/synthetic; point it at any directory with the same layout.

--variants also scores degraded copies (rescaled, JPEG, blur, noise) to
prove the reader is robust to how screenshots are captured.
"""

import io
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.extraction.gets_grid import read_gets_sheet  # noqa: E402


def load_truth(argv):
    if "--dir" in argv:
        d = Path(argv[argv.index("--dir") + 1])
        return d, json.loads((d / "ground_truth.json").read_text())
    from scripts.gen_synthetic_gets import ensure

    d = ensure(ROOT / "test-data" / "synthetic")
    if d is None:
        raise SystemExit("could not generate the synthetic GETS sheets (needs Playwright + Chromium)")
    return d, json.loads((d / "ground_truth.json").read_text())


def variants(img: Image.Image):
    yield "original", img
    w, h = img.size
    for s in (0.8, 1.25, 1.5, 2.0):
        yield f"scale{s}", img.resize((int(w * s), int(h * s)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=60)
    yield "jpeg60", Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    yield "blur", img.filter(ImageFilter.GaussianBlur(0.7))
    arr = np.asarray(img).astype(np.int16)
    rng = np.random.default_rng(7)
    noisy = np.clip(arr + rng.normal(0, 6, arr.shape), 0, 255).astype(np.uint8)
    yield "noise", Image.fromarray(noisy)


def score(sheet, truth) -> list[str]:
    errs = []
    for key in ("employee_name", "person_id", "supplier", "job_family", "month", "year", "days_in_month"):
        if getattr(sheet, key) != truth[key]:
            errs.append(f"{key}: {getattr(sheet, key)!r} != {truth[key]!r}")
    if len(sheet.lines) != len(truth["lines"]):
        errs.append(f"lines: {len(sheet.lines)} != {len(truth['lines'])}")
    for ln, tl in zip(sheet.lines, truth["lines"], strict=False):
        for key in ("uom", "project_id", "sub_project", "sub_project_id"):
            if getattr(ln, key) != tl[key]:
                errs.append(f"row{ln.row_index + 1}.{key}: {getattr(ln, key)!r} != {tl[key]!r}")
        got = {str(d): v for d, v in ln.hours_by_day.items()}
        if got != tl["days"]:
            errs.append(f"row{ln.row_index + 1}.days: {got} != {tl['days']}")
        if ln.printed_total != tl["total"]:
            errs.append(f"row{ln.row_index + 1}.total: {ln.printed_total} != {tl['total']}")
        if tl.get("status") and tl["days"]:
            st = {c.status for c in ln.cells if c.hours is not None}
            if st != {tl["status"]}:
                errs.append(f"row{ln.row_index + 1}.status: {st} != {tl['status']}")
    for label, total in truth["totals"].items():
        if sheet.totals_printed_total.get(label) != total:
            errs.append(f"totals.{label}: {sheet.totals_printed_total.get(label)} != {total}")
    if not sheet.verified:
        errs.append(f"not verified: {[c for c in sheet.checks if not c['ok']]}")
    return errs


def main() -> int:
    with_variants = "--variants" in sys.argv
    base, truth_map = load_truth(sys.argv)
    failures = 0
    for name, truth in truth_map.items():
        img = Image.open(base / name).convert("RGB")
        for vname, vimg in (variants(img) if with_variants else [("original", img)]):
            t = time.time()
            sheet = read_gets_sheet(np.asarray(vimg))
            errs = score(sheet, truth)
            dt = time.time() - t
            flag = "PASS" if not errs else "FAIL"
            failures += bool(errs)
            print(f"{flag} {name:40s} {vname:9s} {dt:5.2f}s status={sheet.status} warn={sheet.warnings}")
            for e in errs:
                print("     ", e)
    print("failures:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
