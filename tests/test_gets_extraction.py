"""GETS timesheet regression: real OCR extracts day-hours into the right
schema, the export emits all 31 day columns + total, and employee rows are
not false-flagged for review.

Gated on the real engine + tesseract (CI without them skips, like the other
real-engine tests).
"""

import io
import shutil

import pytest

from tests.conftest import (
    MA_EMAIL,
    MA_PASSWORD,
)


async def _make_manager(client):
    login = await client.post(
        "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = await client.post(
        "/api/v1/users",
        json={"email": "gets.reg@veritrack.io", "role": "MANAGER"},
        headers=h,
    )
    m = await client.post(
        "/api/v1/auth/login",
        json={"email": "gets.reg@veritrack.io", "password": created.json()["initial_password"]},
    )
    return {"Authorization": f"Bearer {m.json()['access_token']}"}


class TestGetsExtraction:
    async def test_gets_png_extracts_hours_and_exports_timesheet_schema(
        self, client, ma_user_id
    ):
        pytest.importorskip("rapidocr_onnxruntime")
        pytest.importorskip("pytesseract")
        if shutil.which("tesseract") is None:
            pytest.skip("tesseract binary not installed")

        from app.core.config import settings

        if settings.ocr_engine not in ("auto", "rapid"):
            pytest.skip("real engine not requested in this env")

        from app.services.extraction.ocr import reset_ocr_engine_for_tests

        reset_ocr_engine_for_tests()
        headers = await _make_manager(client)

        import pathlib

        png = pathlib.Path("test-data/July_2026.png").read_bytes()
        r = await client.post(
            "/api/v1/uploads?kind=GETS",
            files=[("files", ("July_2026.png", io.BytesIO(png), "image/png"))],
            headers=headers,
        )
        assert r.status_code == 201, r.text
        batch_id = r.json()["id"]

        detail = (await client.get(
            f"/api/v1/uploads/batches/{batch_id}", headers=headers
        )).json()
        f = detail["files"][0]
        assert f["rows_extracted"] >= 2, f"expected extracted rows, got {f.get('rows_extracted')}"
        assert f["needs_review_count"] == 0, f"employee rows should not be flagged"

        exp = await client.get(
            f"/api/v1/batches/{batch_id}/export?format=csv", headers=headers
        )
        assert exp.status_code == 200, exp.text
        text = exp.text
        header = text.splitlines()[0]
        cols = [c.strip().strip('"') for c in header.split(",")]
        day_cols = [c for c in cols if c.startswith("day_")]
        assert "employee_code" in cols and "full_name" in cols
        assert "hour_type" in cols and "project_id" in cols
        assert len(day_cols) == 31, f"expected 31 day columns, got {len(day_cols)}"
        assert cols[-1] == "total"
        # STD row carries 21 '8's — the schema the product ships
        body = text.splitlines()
        assert any(row.count("8") >= 20 for row in body), "no populated daily grid in export"