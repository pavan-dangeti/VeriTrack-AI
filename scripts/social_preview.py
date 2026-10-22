"""Draws the repository's 1280x640 social preview (GitHub → Settings → Social preview).

    python scripts/social_preview.py [OUT.png]      # default: docs/media/social-preview.png

Both figures are from the 200-user load test (README → Load test, `gh workflow run load-test.yml`).
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 640
BG, CARD, EDGE, FG, MUTED = "#0b1020", "#141a2e", "#262f4a", "#f3f4f6", "#9ca3af"
ACCENT, ACCENT2 = "#6366f1", "#7c3aed"   # the logo's two colours
FONTS = {   # macOS, then Linux; Pillow's built-in font if neither is installed
    False: ["/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    True: ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
}
STATS = [("480 / 480", "files processed exactly once"), ("0", "cross-user leaks, 200 concurrent users")]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONTS[bold]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def draw(out: Path) -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    a, b = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (ACCENT, ACCENT2))
    for y in range(H):   # accent bar down the left edge
        t = y / H
        d.line([(0, y), (14, y)], fill=tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3)))

    x = 96
    d.text((x, 92), "VeriTrack AI", font=font(92, bold=True), fill=FG)
    d.text((x, 214), "Timesheet screenshots in, verified leave compliance out.", font=font(38), fill=MUTED)
    for i, (number, label) in enumerate(STATS):
        sx = x + i * 560
        d.rounded_rectangle([sx, 320, sx + 520, 500], radius=20, fill=CARD, outline=EDGE, width=2)
        d.text((sx + 32, 344), number, font=font(76, bold=True), fill=(ACCENT, ACCENT2)[i])
        d.text((sx + 32, 444), label, font=font(23), fill=FG)
    d.text((x, 556), "FastAPI · PostgreSQL row-level security · React · personal project, synthetic data",
           font=font(24), fill=MUTED)
    img.save(out)


if __name__ == "__main__":
    draw(Path(sys.argv[1] if len(sys.argv) > 1 else "docs/media/social-preview.png"))
