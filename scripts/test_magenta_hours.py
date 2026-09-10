"""Prove magenta-filled cells are read as their actual number, not assumed 8.

1. Extract from the real sample (all cells are 8) -> every cell must read 8,
   and STD/NC row sums must match their row totals (168 / 16).
2. Repaint one cell's glyph as '6' in-memory -> that cell must read 6, the
   rest must still read 8.

Run: python3 scripts/test_magenta_hours.py
"""
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_full import (MAGENTA_REF, extract_rows_magenta, find_magenta_bboxes,
                          magenta_dist)

SAMPLE = Path(__file__).resolve().parent.parent / 'test-data' / 'July_2026.png'


def repaint_cell(rgb, bbox, digit):
    x0, y0, x1, y1 = [int(v) for v in bbox]
    out = rgb.copy()
    out[y0:y1 + 1, x0:x1 + 1] = MAGENTA_REF
    font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1
    (tw, th), _ = cv2.getTextSize(digit, font, scale, thick)
    org = (x0 + (x1 - x0 - tw) // 2, y0 + (y1 - y0 + th) // 2)
    cv2.putText(out, digit, org, font, scale, (255, 255, 255), thick, cv2.LINE_AA)
    return out


def run(img_np):
    rows = extract_rows_magenta(img_np, RapidOCR())
    data = {k: v for k, v in rows.items() if k < 500}
    flat = {}
    for rk, days in data.items():
        for d, v in days.items():
            flat[(rk, d)] = v
    return data, flat


def check(cond, msg):
    assert cond, msg
    print(f"  ok: {msg}")


def main():
    rgb = np.asarray(Image.open(SAMPLE).convert('RGB')).astype(np.uint8)

    print('original file (all cells render 8):')
    rows, flat = run(rgb)
    assert flat, 'no magenta cells extracted'
    check(all(v == 8 for v in flat.values()), f'all {len(flat)} cells read 8')
    sums = {rk: sum(days.values()) for rk, days in rows.items() if rk < 500}
    check(sorted(sums.values()) == [16, 168], f'row sums {sums} match totals 168/16')

    bbox = find_magenta_bboxes(magenta_dist(rgb.astype(np.int32)))[0]
    mod = repaint_cell(rgb, bbox, '6')
    Image.fromarray(mod).save('/tmp/magenta_six.png')

    print('modified file (day-1 cell repainted as 6):')
    rows2, flat2 = run(mod)
    changed = [(k, flat[k], flat2.get(k)) for k in flat if flat2.get(k) != flat[k]]
    check(len(changed) == 1, f'exactly one cell changed: {changed}')
    check(changed[0][2] == 6, f'repainted cell reads 6 (was {flat[changed[0][0]]})')


if __name__ == '__main__':
    main()
    print('PASS')
