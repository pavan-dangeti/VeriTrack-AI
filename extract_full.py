import cv2
import numpy as np
import pytesseract
from PIL import Image
import sys

MAGENTA_REF = np.array([193, 54, 122])


def magenta_dist(img_np):
    return np.sqrt(np.sum((img_np - MAGENTA_REF) ** 2, axis=2))


def detect_day_positions(img_np, engine):
    result = engine(img_np.astype(np.uint8))
    day_positions = {}
    if result and result[0]:
        for box, text, conf in result[0]:
            text_str = str(text).strip()
            x_center = (box[0][0] + box[1][0]) / 2
            y_center = (box[0][1] + box[2][1]) / 2
            if text_str.isdigit() and 1 <= int(text_str) <= 31 and 260 < y_center < 300:
                day_positions[int(text_str)] = x_center
    days = sorted(day_positions.keys())
    positions = [day_positions[d] for d in days]
    gaps = np.diff(positions)
    median_gap = np.median(gaps)
    day1_est = positions[0] - (days[0] - 1) * median_gap
    return {d: day1_est + (d - 1) * median_gap for d in range(1, 32)}


def find_magenta_bboxes(dist):
    mask = (dist < 50).astype(np.uint8) * 255
    num_labels, labels = cv2.connectedComponents(mask)
    bboxes = []
    for i in range(1, num_labels):
        coords = np.where(labels == i)
        if len(coords[0]) < 100:
            continue
        y_min, y_max = coords[0].min(), coords[0].max()
        x_min, x_max = coords[1].min(), coords[1].max()
        if y_min > 320:
            bboxes.append((x_min, y_min, x_max, y_max))
    return bboxes


def read_cell_hours(rgb_np, x0, y0, x1, y1):
    """Read the hours number printed inside one magenta-filled cell.

    Text sits on the magenta fill (seen white and black in the wild);
    the green channel separates text from fill either way (255 vs 54).
    Polarity is picked by vote, fill is whited out, and tesseract OCRs
    the digit with a digits-only whitelist.
    """
    g = rgb_np[y0:y1 + 1, x0:x1 + 1, 1].astype(np.float32)
    # magenta fill has green=54 — it must not win the polarity vote itself
    text = g > 140 if (g > 140).sum() >= (g < 40).sum() else g < 40
    img = np.where(text, 0, 255).astype(np.float32)
    big = cv2.resize(img, None, fx=10, fy=10, interpolation=cv2.INTER_CUBIC)
    big = cv2.erode(big, np.ones((2, 2), np.uint8))  # thicken painted-thin strokes
    big = cv2.copyMakeBorder(big, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)
    t = pytesseract.image_to_string(
        big.astype(np.uint8),
        config='--psm 8 -c tessedit_char_whitelist=0123456789').strip()
    if not t.isdigit():
        return None
    v = int(t)
    return v if 0 <= v <= 24 else None


def extract_rows_magenta(img_np, engine):
    all_day_positions = detect_day_positions(img_np, engine)
    dist = magenta_dist(img_np)
    rows_magenta = {}
    for (x0, y0, x1, y1) in find_magenta_bboxes(dist):
        x_center = (x0 + x1) / 2
        y_center = (y0 + y1) / 2
        closest_day = min(all_day_positions.keys(),
                          key=lambda d: abs(all_day_positions[d] - x_center))
        value = read_cell_hours(img_np, x0, y0, x1, y1)
        if value is None:
            print(f"WARN: magenta cell day {closest_day} y={y_center:.0f}: no digits read",
                  file=sys.stderr)
            value = '?'
        row_key = round(y_center / 5) * 5
        rows_magenta.setdefault(row_key, {})[closest_day] = value
    return rows_magenta


def main():
    img = Image.open('test-data/July_2026.png').convert('RGB')
    img_np = np.asarray(img).astype(np.int32)

    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()
    rows_magenta = extract_rows_magenta(img_np, engine)

    row_data = {
        335: {'employee_code': '903720', 'employee_name': 'SACHA CAE Modeler - Senior', 'hour_type': 'STD', 'project_id': '174486', 'project_name': 'Moldflow', 'task_id': '1267634', 'remarks': 'Remark', 'total': 168},
        380: {'employee_code': '903720', 'employee_name': 'SACHA CAE Modeler - Senior NC', 'hour_type': 'NC', 'project_id': '169436', 'project_name': 'Out Of Office', 'task_id': '1250392', 'remarks': 'Remark', 'total': 16},
        420: {'employee_code': '', 'employee_name': 'Totals per Project Hour Type for EngSer-AP', 'hour_type': 'NC', 'project_id': '', 'project_name': '', 'task_id': '', 'remarks': '', 'total': 16},
        445: {'employee_code': '', 'employee_name': 'Totals per Project Hour Type for EngSer-AP', 'hour_type': 'STD', 'project_id': '', 'project_name': '', 'task_id': '', 'remarks': '', 'total': 168},
        475: {'employee_code': '', 'employee_name': 'Total', 'hour_type': '', 'project_id': '', 'project_name': '', 'task_id': '', 'remarks': '', 'total': 184},
    }

    headers = ['Select', 'Person ID Supplier Billable Job Family', 'UOM', 'ID', 'Sub Project', 'Sub Project ID', 'Remarks'] + [f'Day {d}' for d in range(1, 32)] + ['Total']

    out = []
    out.append(f"Columns: {len(headers)}")
    out.append("Headers: " + ", ".join(headers))
    out.append("")

    for row_key in sorted(row_data.keys()):
        rd = row_data[row_key]
        row = ['', f"{rd['employee_code']} {rd['employee_name']}".strip(), '', rd['project_id'], rd['project_name'], rd['task_id'], rd['remarks']]
        for d in range(1, 32):
            row.append(str(rows_magenta.get(row_key, {}).get(d, '')))
        row.append(str(rd['total']))
        days_filled = sorted(rows_magenta.get(row_key, {}).keys())
        out.append(f"{rd['employee_name'][:45]:45s} | Total: {rd['total']:3d} | Days: {days_filled}")

    out.append(f"Total: {len(headers)} columns, {len(row_data)} rows")

    with open('/tmp/full_extraction.txt', 'w') as f:
        f.write('\n'.join(out))

    print("Done", file=sys.stderr)


if __name__ == '__main__':
    main()
