"""Filtered exports of processed GETS batch data: CSV / XLSX / PDF / PNG.
Pure reformatting — no violation logic touches this path."""

import csv
import io
from datetime import datetime

DEFAULT_EXPORT_COLUMNS = [
    "employee_code",
    "full_name",
    "official_email",
    "personal_email",
    "department",
]


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\x0b")


def _escape_formula(value: str) -> str:
    """Neutralize spreadsheet-formula injection: prefix dangerous cell
    values with an apostrophe so Excel/Sheets/LibreOffice treat them as text."""
    if value.lstrip(" ")[:1] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def _flatten_rows(rows: list[dict], columns: list[str]) -> tuple[list[str], list[list]]:
    """columns may include extra fields like 'customer leave'."""
    header = []
    for col in columns:
        if col in ("customer leave", "sacha leave") or "." not in col:
            header.append(col)
        else:
            header.append(col)
    out = []
    for r in rows:
        record = dict(r or {})
        extras = record.pop("extra", {}) or {}
        merged = {**{k: v for k, v in record.items() if k != "extra"}, **extras}
        out.append([_escape_formula(str(merged.get(c, "") or "")) for c in columns])
    return header, out


def export_csv(rows: list[dict], columns: list[str]) -> bytes:
    header, body = _flatten_rows(rows, columns)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(body)
    return buf.getvalue().encode("utf-8")


def export_xlsx(rows: list[dict], columns: list[str]) -> bytes:
    from openpyxl import Workbook

    header, body = _flatten_rows(rows, columns)
    wb = Workbook()
    ws = wb.active
    ws.title = "GETS Export"
    ws.append(header)
    for row in body:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_pdf(rows: list[dict], columns: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas

    header, body = _flatten_rows(rows, columns)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    width, height = landscape(A4)
    y = height - 20
    c.setFont("Helvetica-Bold", 8)
    c.drawString(20, y, f"VeriTrack GETS export — {datetime.now():%Y-%m-%d %H:%M}")
    y -= 16

    col_w = max((width - 40) / max(len(header), 1), 60)

    def draw_row(cells, bold=False):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 7.5)
        for i, cell in enumerate(cells):
            c.drawString(20 + i * col_w, y, str(cell)[: int(col_w // 4.2)])
        y -= 11

    draw_row(header, bold=True)
    for row in body:
        if y < 30:
            c.showPage()
            y = height - 30
            c.setFont("Helvetica-Bold", 7.5)
        draw_row(row)
    c.save()
    return buf.getvalue()


def export_png(rows: list[dict], columns: list[str]) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    header, body = _flatten_rows(rows, columns)
    try:
        font = ImageFont.load_default(12)
        bold = ImageFont.load_default(13)
    except TypeError:  # Pillow <10 fallbacks
        font = ImageFont.load_default()
        bold = font

    padding, row_h, min_col_w = 10, 22, 90
    col_ws = [
        max(
            min_col_w,
            *(font.getbbox(str(r[i] if i < len(r) else ""))[2] + 2 * padding
              for r in [header] + body),
        )
        for i in range(len(header))
    ]
    img_w = sum(col_ws) + 2 * padding
    img_h = row_h * (len(body) + 1) + 2 * padding
    img = Image.new("RGB", (img_w, img_h), "white")
    draw = ImageDraw.Draw(img)

    x = padding
    for i, cell in enumerate(header):
        draw.rectangle([x, padding, x + col_ws[i], padding + row_h], fill="#0B0F1A")
        draw.text((x + 5, padding + 4), str(cell), fill="white", font=bold)
        x += col_ws[i]

    y = padding + row_h
    for r_i, row in enumerate(body):
        x = padding
        fill = "#F3F4F6" if r_i % 2 else "white"
        for i, cell in enumerate(row):
            draw.rectangle([x, y, x + col_ws[i], y + row_h], fill=fill, outline="#D1D5DB")
            draw.text((x + 5, y + 4), str(cell), fill="#111827", font=font)
            x += col_ws[i]
        y += row_h

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


EXPORTERS = {
    "csv": ("text/csv", "gets-export.csv", export_csv),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "gets-export.xlsx",
        export_xlsx,
    ),
    "pdf": ("application/pdf", "gets-export.pdf", export_pdf),
    "png": ("image/png", "gets-export.png", export_png),
}
