"""Standalone messy-scan image generator.

Lives outside tests/ so live demo scripts can use it WITHOUT importing
pytest conftest (which repoints DATABASE_URL / OCR_ENGINE at test settings).
"""

import io

from PIL import Image, ImageDraw, ImageFont

ROWS = [
    ("S-101", "Alice Munro", "alice.m@corp.io", "", "YES"),
    ("S-202", "Bob Tan", "", "bob.t@gmail.com", "✓"),
    ("S-303", "Carol Dias", "carol@corp.io", "", ""),
    ("S-404", "Dev Patel", "dev.p@corp.io", "dev@gmail.com", "[x]"),
    ("S-505", "Eva Roy", "", "", "x"),
]

HEADER = "Code   Full Name   Company Email   Personal Email"


def build_messy_scan() -> bytes:
    """Renders ROWS into a rotated, noisy, JPEG-compressed 'scan'."""
    img = Image.new("RGB", (900, 340), (247, 246, 242))
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(26)

    d.text((30, 25), HEADER, fill="black", font=font)
    y = 90
    for code, name, offic, personal, tick in ROWS:
        d.text((30, y), f"{code}   {name}   {offic}   {personal}",
               fill="black", font=font)
        d.text((720, y), "X" if tick.strip("[]").lower() in ("x", "yes") else "",
               fill="black", font=font)
        y += 48

    img = img.rotate(2.0, expand=True, fillcolor=(247, 246, 242))
    px = img.load()
    for i in range(0, img.width, 7):
        for j in range(0, img.height, 11):
            r, g, b = px[i, j]
            px[i, j] = (r - 14 if r > 20 else r, g, b)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=55)
    return buf.getvalue()
