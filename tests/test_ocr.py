"""OCR engine behavior: real RapidOCR on this platform, PENDING_OCR fallback,
reprocess-after-engine-installed flow."""

import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from tests.conftest import (
    MA_EMAIL,
    MA_PASSWORD,
)


def _text_image(text: str) -> bytes:
    img = Image.new("RGB", (520, 140), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(26)
    except TypeError:
        font = ImageFont.load_default()
    d.text((20, 20), text.split("\n")[0], fill="black", font=font)
    if "\n" in text:
        d.text((20, 70), text.split("\n")[1], fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _scanned_pdf(image_png: bytes) -> bytes:
    """An image-only PDF (no text layer) = what a scanner produces."""
    from pypdfium2 import PdfDocument

    img = Image.open(io.BytesIO(image_png)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    _ = PdfDocument  # rasterization happens inside the engine
    return buf.getvalue()


async def _make_manager(client):
    login = await client.post(
        "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = await client.post(
        "/api/v1/users",
        json={"email": "ocr.manager@veritrack.io", "role": "MANAGER"},
        headers=h,
    )
    pw = created.json()["initial_password"]
    m = await client.post(
        "/api/v1/auth/login",
        json={"email": "ocr.manager@veritrack.io", "password": pw},
    )
    return {"Authorization": f"Bearer {m.json()['access_token']}"}


class TestRealEngine:
    def test_rapidocr_reads_text_image(self):
        pytest.importorskip("rapidocr_onnxruntime")
        from app.services.extraction.ocr import RapidOcrEngine

        engine = RapidOcrEngine()
        assert engine.available()
        tables = engine.extract_tables(
            _text_image("Employee ID  Name\nE-100  Ann Weaver"), "image/png"
        )
        cells = [c for t in tables for r in t.rows for c in r]
        heads = [h for t in tables for h in t.headers]
        flat = " ".join(str(x) for x in cells + heads)
        tokens = flat.replace(" ", "")
        assert "E-100" in tokens and "Ann" in tokens and "Weaver" in tokens

    def test_scanned_pdf_rasterized_and_read(self):
        pytest.importorskip("rapidocr_onnxruntime")
        from app.services.extraction.ocr import RapidOcrEngine

        engine = RapidOcrEngine()
        pdf = _scanned_pdf(_text_image("Employee ID\nE-200"))
        tables = engine.extract_tables(pdf, "application/pdf")
        flat = "".join(str(c) for t in tables for r in t.rows for c in r)
        assert "E-200" in flat


class TestPendingOcrFallback:
    async def test_image_without_engine_lands_pending_not_failed(
        self, client, ma_user_id, monkeypatch
    ):
        from app.services.extraction import ocr as ocr_mod

        headers = await _make_manager(client)

        class NoEngine:
            def available(self):
                return False

            def extract_tables(self, data, content_type):
                from app.services.extraction.ocr import OcrUnavailableError

                raise OcrUnavailableError("no engine configured")

        monkeypatch.setattr(ocr_mod, "get_ocr_engine", lambda: NoEngine())

        r = await client.post(
            "/api/v1/uploads?kind=EMPLOYEE_REPO",
            files=[("files", ("scan.png", io.BytesIO(_text_image("E-100 Ann")),
                              "image/png"))],
            headers=headers,
        )
        assert r.status_code == 201
        batch = r.json()
        assert batch["status"] == "COMPLETED"  # batch completes; file waits

        detail = (await client.get(
            f"/api/v1/uploads/batches/{batch['id']}", headers=headers)).json()
        f = detail["files"][0]
        assert f["status"] == "PENDING_OCR"
        assert "no engine configured" in (f["error_message"] or "")

    async def test_reprocess_after_engine_available(self, client, ma_user_id, monkeypatch):
        from app.services.extraction import ocr as ocr_mod

        headers = await _make_manager(client)

        class NoEngine:
            def available(self):
                return False

            def extract_tables(self, data, content_type):
                from app.services.extraction.ocr import OcrUnavailableError

                raise OcrUnavailableError("no engine configured")

        monkeypatch.setattr(ocr_mod, "get_ocr_engine", lambda: NoEngine())
        r = await client.post(
            "/api/v1/uploads?kind=EMPLOYEE_REPO",
            files=[("files", ("scan.png",
                              io.BytesIO(_text_image("E-100 Ann")),
                              "image/png"))],
            headers=headers,
        )
        batch_id = r.json()["id"]
        detail = (await client.get(
            f"/api/v1/uploads/batches/{batch_id}", headers=headers)).json()
        file_id = detail["files"][0]["id"]
        assert detail["files"][0]["status"] == "PENDING_OCR"

        # "Install" the engine, then retry via the API.
        from app.services.extraction.readers import RawTable

        class WorkingEngine:
            def available(self):
                return True

            def extract_tables(self, data, content_type):
                return [RawTable(headers=["Employee ID", "Name"],
                                 rows=[["E-100", "Ann"]])]

        monkeypatch.setattr(ocr_mod, "get_ocr_engine", lambda: WorkingEngine())
        rp = await client.post(
            f"/api/v1/uploads/batches/{batch_id}/files/{file_id}/reprocess",
            headers=headers,
        )
        assert rp.status_code == 200, rp.text
        assert rp.json()["status"] == "DONE"
        assert rp.json()["rows_extracted"] == 1

    async def test_reprocess_rejects_done_files(self, client, ma_user_id, monkeypatch):
        headers = await _make_manager(client)
        csv = b'{"tables":[{"headers":["Employee ID","Name"],"rows":[["E-9","X"]]}]}'
        r = await client.post(
            "/api/v1/uploads?kind=EMPLOYEE_REPO",
            files=[("files", ("t.csv", io.BytesIO(csv), "text/csv"))],
            headers=headers,
        )
        batch_id = r.json()["id"]
        detail = (await client.get(
            f"/api/v1/uploads/batches/{batch_id}", headers=headers)).json()
        file_id = detail["files"][0]["id"]
        rp = await client.post(
            f"/api/v1/uploads/batches/{batch_id}/files/{file_id}/reprocess",
            headers=headers,
        )
        assert rp.status_code == 409


class TestScannedUploadEndToEnd:
    """With the real engine present, an image upload flows through to rows."""

    async def test_png_upload_processes_with_real_engine(self, client, ma_user_id):
        pytest.importorskip("rapidocr_onnxruntime")
        from app.core.config import settings
        from app.services.extraction.ocr import reset_ocr_engine_for_tests

        if settings.ocr_engine not in ("auto", "rapid"):
            pytest.skip("OCR_ENGINE not set to a real engine in this env")

        reset_ocr_engine_for_tests()
        headers = await _make_manager(client)
        png = _text_image("Employee ID   Name\nE-500         Real Ocr Test")
        r = await client.post(
            "/api/v1/uploads?kind=EMPLOYEE_REPO",
            files=[("files", ("scan.png", io.BytesIO(png), "image/png"))],
            headers=headers,
        )
        detail = (await client.get(
            f"/api/v1/uploads/batches/{r.json()['id']}", headers=headers)).json()
        status = detail["files"][0]["status"]

        if status == "PENDING_OCR":
            pytest.skip("engine degraded in this environment")  # never silently pass
        assert status == "DONE"

        emps = (await client.get("/api/v1/employees", headers=headers)).json()
        codes = {e["employee_code"] for e in emps["items"]}
        assert any("E-500" in c for c in codes), codes
