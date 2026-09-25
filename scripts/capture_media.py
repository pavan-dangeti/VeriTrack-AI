"""Regenerates the README screenshots and demo video from a running app.

    ADMIN_EMAIL=... ADMIN_PASSWORD=... python -m scripts.capture_media \
        --base http://localhost:4173 --out docs/media

Uses a fresh database with only the synthetic sheets in test-data/synthetic,
so no real employee data can end up in the images. Needs ffmpeg for the
video.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import httpx
from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "test-data/synthetic"
SHEETS = ["synthetic_000.png", "synthetic_004.png", "synthetic_007.png", "synthetic_013.png"]
REPO_CSV = (
    "Employee ID,Full Name,Company Email,Personal Email,Department\n"
    "103729,Golf Anonymous,golf.anonymous@example.com,,Engineering\n"
    "158082,Kilo Specimen,kilo.specimen@example.com,,Engineering\n"
    "141220,Bravo Example,,bravo.example@example.net,Design\n"
    "197061,Echo Specimen,echo.specimen@example.com,,Design\n"
)
LEAVE_CSV = (
    "Employee ID,From Date,To Date,Leave Type\n"
    "103729,09-03-2026,,Casual\n103729,2026-03-24,,Casual\n"
    "141220,01/07/2025,01/07/2025,Sick\n141220,03-Jul-2025,,Casual\n141220,2025-07-14,,Casual\n"
    "197061,02-Jun-2025,03-Jun-2025,Earned\n197061,11/06/2025,,Casual\n"
)
CHROMIUM = os.environ.get("CHROMIUM_PATH") or None


def api_setup(base: str) -> dict:
    c = httpx.Client(base_url=base, timeout=60)

    def login(email, pw):
        r = c.post("/api/v1/auth/login", json={"email": email, "password": pw})
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    admin = login(os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"])
    stamp = time.strftime("%H%M%S")
    accounts = {}
    for role, name in (("MANAGER", "Alex Morgan"), ("EXECUTIVE", "Jordan Lee")):
        email = f"{name.split()[0].lower()}.{stamp}@example.com"
        r = c.post("/api/v1/users", json={"email": email, "role": role, "full_name": name}, headers=admin)
        r.raise_for_status()
        accounts[role] = (email, r.json()["initial_password"])
    mgr = login(*accounts["MANAGER"])
    r = c.post("/api/v1/users", json={"email": f"sam.{stamp}@example.com", "role": "HR", "full_name": "Sam Taylor"},
               headers=mgr)
    r.raise_for_status()
    for kind, name, body in (("EMPLOYEE_REPO", "repository.csv", REPO_CSV), ("COMPANY_LEAVE", "leave.csv", LEAVE_CSV)):
        c.post(f"/api/v1/uploads?kind={kind}", files=[("files", (name, body.encode(), "text/csv"))],
               headers=mgr).raise_for_status()
    return {"manager": accounts["MANAGER"], "admin": (os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"])}


def sign_in(page: Page, email: str, pw: str) -> None:
    page.goto("/login")
    expect(page.get_by_role("heading", name="Welcome back")).to_be_visible()
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password").fill(pw)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(re.compile(r"/dashboard$"))
    page.wait_for_load_state("networkidle")


def pause(page: Page, ms: int = 1200) -> None:
    page.wait_for_timeout(ms)


class Recorder:
    """Frame grabs instead of a screencast, cheap enough that the OCR being
    filmed keeps the CPU. Long waits are shortened when the video is encoded."""

    def __init__(self, page: Page, folder: Path) -> None:
        self.page, self.folder = page, folder
        self.frames: list[tuple[Path, float]] = []
        folder.mkdir(parents=True, exist_ok=True)

    def grab(self) -> None:
        path = self.folder / f"{len(self.frames):05d}.png"
        self.page.screenshot(path=str(path))
        self.frames.append((path, time.monotonic()))

    def hold(self, seconds: float, fps: float = 5) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.grab()
            self.page.wait_for_timeout(1000 / fps)

    def type(self, locator, text: str) -> None:
        locator.click()
        for i, ch in enumerate(text):
            locator.press(ch)
            if i % 3 == 0:
                self.grab()

    def until(self, locator, timeout_s: float = 900) -> None:
        start = time.monotonic()
        while not locator.count():
            if time.monotonic() - start > timeout_s:
                raise TimeoutError("demo step did not finish")
            self.grab()
            self.page.wait_for_timeout(1500)

    def write_concat(self, target: Path) -> None:
        stamps = [t for _, t in self.frames] + [self.frames[-1][1] + 2.5]
        lines = []
        for i, (path, _) in enumerate(self.frames):
            gap = stamps[i + 1] - stamps[i]
            lines += [f"file '{path.name}'", f"duration {0.5 if gap > 1.2 else max(gap, 0.05):.3f}"]
        lines.append(f"file '{self.frames[-1][0].name}'")
        target.write_text("\n".join(lines) + "\n")


def demo_video(browser, base: str, creds: tuple[str, str], frames: Path) -> tuple[Recorder, str]:
    ctx = browser.new_context(base_url=base, viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    rec = Recorder(page, frames)
    page.goto("/login")
    expect(page.get_by_role("heading", name="Welcome back")).to_be_visible()
    rec.hold(1.0)
    rec.type(page.get_by_label("Email"), creds[0])
    rec.type(page.get_by_label("Password"), creds[1])
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(re.compile(r"/dashboard$"))
    page.wait_for_load_state("networkidle")
    rec.hold(2.0)
    page.get_by_role("link", name="GETS Uploads").click()
    page.wait_for_load_state("networkidle")
    rec.hold(1.5)
    page.get_by_test_id("gets-file-input").set_input_files([str(SYN / n) for n in SHEETS])
    card = page.locator("[data-testid^='batch-']").first
    rec.hold(1.5)
    rec.until(card.locator("[data-status=COMPLETED]"))
    batch_id = card.get_attribute("data-testid").removeprefix("batch-")
    rec.hold(2.5)
    card.get_by_test_id("progress-card").locator("tbody tr").filter(has_text="synthetic_007.png") \
        .get_by_role("button", name="Review").click()
    page.get_by_role("tab", name="Grid").click()   # the reconstructed grid only, never the screenshot
    expect(page.get_by_test_id("timesheet-grid")).to_be_visible()
    page.wait_for_load_state("networkidle")
    rec.hold(3.0)
    page.mouse.wheel(0, 450)
    rec.hold(2.5)
    page.get_by_test_id("back-button").click()
    page.wait_for_load_state("networkidle")
    rec.hold(1.0)
    page.get_by_test_id(f"analyze-{batch_id}").click()
    rec.until(page.get_by_test_id("violations-table"), timeout_s=120)
    page.wait_for_load_state("networkidle")
    rec.hold(4.0)
    ctx.close()
    return rec, batch_id


def screenshots(browser, base: str, creds: dict, batch_id: str, out: Path) -> None:
    def shot(page: Page, name: str) -> None:
        page.wait_for_load_state("networkidle")
        pause(page, 600)
        page.screenshot(path=str(out / f"{name}.png"), animations="disabled")

    ctx = browser.new_context(base_url=base, viewport={"width": 1440, "height": 900}, color_scheme="light")
    page = ctx.new_page()
    page.goto("/login")
    shot(page, "login")
    sign_in(page, *creds["manager"])
    shot(page, "dashboard")
    page.goto("/gets")
    page.locator("[data-testid^='batch-']").first.get_by_test_id("inspect").click()
    shot(page, "gets-uploads")
    page.goto(f"/analysis/{batch_id}")
    shot(page, "analysis-results")
    page.goto("/gets")
    card = page.locator("[data-testid^='batch-']").first
    card.get_by_test_id("inspect").click()
    card.get_by_test_id("progress-card").locator("tbody tr").filter(has_text="synthetic_007.png") \
        .get_by_role("button", name="Review").click()
    page.get_by_role("tab", name="Grid").click()
    expect(page.get_by_test_id("timesheet-grid")).to_be_visible()
    shot(page, "sheet-review")
    page.goto("/leaves")
    page.get_by_test_id("leave-month").fill("2025-07")
    page.locator("h1").click()
    shot(page, "leave-register")
    page.goto("/employees")
    shot(page, "employee-repository")
    page.goto("/dashboard")
    page.get_by_test_id("open-palette").click()
    page.get_by_label("Search pages").press_sequentially("lea", delay=40)
    shot(page, "command-palette")
    page.keyboard.press("Escape")
    page.get_by_test_id("theme-toggle").click()
    page.goto(f"/analysis/{batch_id}")
    shot(page, "analysis-results-dark")
    page.get_by_test_id("theme-toggle").click()
    ctx.close()

    ctx = browser.new_context(base_url=base, viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    sign_in(page, *creds["admin"])
    page.goto("/audit-logs")
    shot(page, "audit-logs")
    page.goto("/analytics")
    pause(page, 3500)
    shot(page, "analytics")
    ctx.close()

    ctx = browser.new_context(base_url=base, viewport={"width": 390, "height": 844}, device_scale_factor=2,
                              is_mobile=True, has_touch=True)
    page = ctx.new_page()
    sign_in(page, *creds["manager"])
    shot(page, "mobile-dashboard")
    ctx.close()


def encode(rec: Recorder, out: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return
    concat = rec.folder / "frames.txt"
    rec.write_concat(concat)
    src = [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat)]
    subprocess.run([*src, "-vf", "fps=25,format=yuv420p", "-c:v", "libx264", "-crf", "24",
                    "-movflags", "+faststart", str(out / "demo.mp4")], check=True)
    palette = rec.folder / "palette.png"
    scale = "fps=8,scale=1000:-1:flags=lanczos"
    subprocess.run([*src, "-vf", f"{scale},palettegen=max_colors=128", str(palette)], check=True)
    subprocess.run([*src, "-i", str(palette), "-lavfi",
                    f"{scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5", str(out / "demo.gif")], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:4173")
    ap.add_argument("--out", default="docs/media")
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    from scripts.gen_synthetic_gets import ensure

    if ensure(SYN) is None:
        raise SystemExit("could not generate the synthetic GETS sheets (needs Playwright + Chromium)")
    frames = out / "_frames"
    shutil.rmtree(frames, ignore_errors=True)
    creds = api_setup(args.base)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM)
        rec, batch_id = demo_video(browser, args.base, creds["manager"], frames)
        screenshots(browser, args.base, creds, batch_id, out)
        browser.close()
    encode(rec, out)
    shutil.rmtree(frames, ignore_errors=True)
    print("media written to", out)


if __name__ == "__main__":
    main()
