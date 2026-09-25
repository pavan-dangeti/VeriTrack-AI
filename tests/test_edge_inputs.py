"""Hostile and imperfect inputs: the reader either gets a sheet exactly right
or says it needs review — it never reports wrong numbers as verified."""

import io
import json

import numpy as np
import pytest
from PIL import Image

from scripts.gen_synthetic_gets import ensure
from tests.helpers import csv_file, manager

SYN = ensure()
TRUTH = json.loads((SYN / "ground_truth.json").read_text()) if SYN else {}
needs_sheets = pytest.mark.skipif(SYN is None, reason="synthetic GETS sheets need Playwright + Chromium")


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _distortions():
    img = Image.open(SYN / "synthetic_007.png").convert("RGB")
    w, h = img.size
    yield "no_totals_rows", img.crop((0, 0, w, int(h * 0.62)))
    yield "right_side_cut", img.crop((0, 0, int(w * 0.8), h))
    yield "left_side_cut", img.crop((int(w * 0.25), 0, w, h))
    yield "rotated_1deg", img.rotate(1, expand=True, fillcolor="white")
    yield "grayscale", img.convert("L").convert("RGB")
    yield "tiny_40pct", img.resize((int(w * 0.4), int(h * 0.4)), Image.LANCZOS)
    yield "padded_in_screenshot", _pad(img)


def _pad(img: Image.Image) -> Image.Image:
    canvas = Image.new("RGB", (img.width + 400, img.height + 300), (40, 44, 52))
    canvas.paste(img, (200, 150))
    return canvas


DISTORTIONS = ["no_totals_rows", "right_side_cut", "left_side_cut", "rotated_1deg", "grayscale", "tiny_40pct",
               "padded_in_screenshot"]


@needs_sheets
@pytest.mark.parametrize("name", DISTORTIONS)
def test_distorted_sheet_is_exact_or_flagged(name):
    pytest.importorskip("rapidocr_onnxruntime")
    from app.services.extraction.gets_grid import GetsLayoutError, read_gets_sheet
    from scripts.eval_gets_accuracy import score

    img = dict(_distortions())[name]
    try:
        sheet = read_gets_sheet(np.asarray(img))
    except GetsLayoutError:
        return  # refused outright: acceptable
    errors = score(sheet, TRUTH["synthetic_007.png"])
    labels = ("employee_name", "supplier", "job_family", ".sub_project:")
    numeric = [e for e in errors if not any(t in e for t in labels)]
    if sheet.status in ("VERIFIED", "CORRECTED"):
        assert not numeric, f"{name}: verified but wrong:\n" + "\n".join(numeric)


class TestUploadLimits:
    async def test_oversized_file_is_rejected(self, client, ma_user_id, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "max_file_size_mb", 1)
        h = await manager(client, "edge.big")
        big = b"Employee ID,Full Name\n" + b"E-1,Ann\n" * 200_000
        r = await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO", files=[csv_file("big.csv", big)], headers=h)
        assert r.status_code == 413
        assert (await client.get("/api/v1/uploads/batches", headers=h)).json() == []

    async def test_corrupt_xlsx_is_rejected(self, client, ma_user_id):
        h = await manager(client, "edge.xlsx")
        r = await client.post(
            "/api/v1/uploads?kind=EMPLOYEE_REPO",
            files=[("files", ("repo.xlsx", io.BytesIO(b"PK\x03\x04garbage" * 50),
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
            headers=h,
        )
        assert r.status_code in (201, 415)
        if r.status_code == 201:
            detail = (await client.get(f"/api/v1/uploads/batches/{r.json()['id']}", headers=h)).json()
            assert detail["files"][0]["status"] == "FAILED"

    async def test_executable_disguised_as_png_is_rejected(self, client, ma_user_id):
        h = await manager(client, "edge.exe")
        r = await client.post(
            "/api/v1/uploads?kind=GETS",
            files=[("files", ("sheet.png", io.BytesIO(b"MZ\x90\x00" + b"\x00" * 2000), "image/png"))],
            headers=h,
        )
        assert r.status_code == 415

    async def test_same_sheet_uploaded_twice_counts_once(self, client, ma_user_id):
        h = await manager(client, "edge.dupe")
        await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO",
                          files=[csv_file("r.csv", "Employee ID,Full Name,Company Email\nE-1,Ann,a@corp.io\n")],
                          headers=h)
        gets = "Employee ID,Name,Customer Leave,Company Leave\nE-1,Ann,x,\n"
        batch = (await client.post("/api/v1/uploads?kind=GETS",
                                   files=[csv_file("a.csv", gets), csv_file("b.csv", gets)], headers=h)).json()
        assert (await client.post(f"/api/v1/batches/{batch['id']}/analyze", headers=h)).status_code == 202
        result = (await client.get(f"/api/v1/batches/{batch['id']}/analysis", headers=h)).json()
        assert result["totals"]["violations"] == 1  # one employee, one email

    @needs_sheets
    async def test_png_screenshot_inside_pdf_is_read(self, client, ma_user_id, monkeypatch):
        pytest.importorskip("rapidocr_onnxruntime")
        from app.core.config import settings
        from app.services.extraction.ocr import reset_ocr_engine_for_tests

        monkeypatch.setattr(settings, "ocr_engine", "rapid")
        reset_ocr_engine_for_tests()
        img = Image.open(SYN / "synthetic_000.png").convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "PDF", resolution=96)
        h = await manager(client, "edge.pdf")
        r = await client.post("/api/v1/uploads?kind=GETS",
                              files=[("files", ("sheet.pdf", io.BytesIO(buf.getvalue()), "application/pdf"))],
                              headers=h)
        assert r.status_code == 201, r.text
        f = (await client.get(f"/api/v1/uploads/batches/{r.json()['id']}", headers=h)).json()["files"][0]
        assert f["status"] == "DONE", f
        assert f["sheet_status"] in ("VERIFIED", "CORRECTED"), f
        assert f["sheet_period"] == "2026-03"
        assert f["sheet_employee"] == TRUTH["synthetic_000.png"]["employee_name"]
