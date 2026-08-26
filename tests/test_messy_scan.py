"""Messy-scan OCR test: a deliberately degraded scanned sheet must still
yield usable repository data through the full API path with the real engine.

Degradation applied: 2-degree rotation, gray noise, JPEG compression
artifacts, inconsistent tick marks, missing fields, uneven column spacing.

Honest expectations are encoded: OCR on degraded scans is allowed to miss
or garble some cells; we assert high-signal fields (employee codes, emails)
survive for most rows rather than demanding pixel-perfect recovery.
"""

import io

import pytest

from scripts.messy_scan_fixture import ROWS, build_messy_scan
from tests.conftest import (
    MA_EMAIL,
    MA_PASSWORD,
)

EXPECTED_CODES = [r[0] for r in ROWS]
EXPECTED_EMAILS = ["alice.m@corp.io", "bob.t@gmail.com", "carol@corp.io"]

async def _make_manager(client):
    login = await client.post(
        "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = await client.post(
        "/api/v1/users",
        json={"email": "scan.test.manager@veritrack.io", "role": "MANAGER"},
        headers=h,
    )
    pw = created.json()["initial_password"]
    m = await client.post(
        "/api/v1/auth/login",
        json={"email": "scan.test.manager@veritrack.io", "password": pw},
    )
    return {"Authorization": f"Bearer {m.json()['access_token']}"}


class TestMessyScan:
    async def test_degraded_scan_yields_usable_repository(
        self, client, ma_user_id, monkeypatch
    ):
        pytest.importorskip("rapidocr_onnxruntime")
        from app.core.config import settings
        from app.services.extraction.ocr import (
            RapidOcrEngine,
            reset_ocr_engine_for_tests,
        )

        assert RapidOcrEngine().available(), "real engine required for this test"
        # Force the real engine for the pipeline regardless of suite defaults.
        monkeypatch.setattr(settings, "ocr_engine", "rapid")
        reset_ocr_engine_for_tests()
        headers = await _make_manager(client)
        scan = build_messy_scan()

        r = await client.post(
            "/api/v1/uploads?kind=EMPLOYEE_REPO",
            files=[("files", ("messy_scan.jpg", io.BytesIO(scan), "image/jpeg"))],
            headers=headers,
        )
        assert r.status_code == 201, r.text
        batch = r.json()
        detail = (await client.get(
            f"/api/v1/uploads/batches/{batch['id']}", headers=headers)).json()
        file_info = detail["files"][0]

        if file_info["status"] == "PENDING_OCR":
            pytest.fail("engine was available but pipeline claimed otherwise")

        assert file_info["status"] == "DONE", file_info["error_message"]
        assert (file_info["rows_extracted"] or 0) >= 3, (
            f"expected most rows recovered, got {file_info['rows_extracted']} "
            f"(error={file_info['error_message']})"
        )

        listing = (await client.get("/api/v1/employees", headers=headers)).json()
        codes = {e["employee_code"] for e in listing["items"]}
        recovered = codes & set(EXPECTED_CODES)
        assert len(recovered) >= 4, (
            f"only {sorted(recovered)} of {EXPECTED_CODES} recovered; "
            f"got {sorted(codes)}"
        )

        # emails survive for rows that had them
        emails_found = {
            e["official_email"] or e["personal_email"] for e in listing["items"]
        }
        overlap = {e for e in emails_found if e} & set(EXPECTED_EMAILS)
        assert len(overlap) >= 2, f"emails lost in scan: {emails_found}"

    async def test_same_scan_reprocess_is_stable(
        self, client, ma_user_id, monkeypatch
    ):
        """Re-uploading identical scan bytes yields identical row count."""
        pytest.importorskip("rapidocr_onnxruntime")
        from app.core.config import settings
        from app.services.extraction.ocr import reset_ocr_engine_for_tests

        monkeypatch.setattr(settings, "ocr_engine", "rapid")
        reset_ocr_engine_for_tests()
        headers = await _make_manager(client)
        scan = build_messy_scan()

        counts = []
        for _ in range(2):
            r = await client.post(
                "/api/v1/uploads?kind=EMPLOYEE_REPO",
                files=[("files", ("again.jpg", io.BytesIO(scan), "image/jpeg"))],
                headers=headers,
            )
            detail = (await client.get(
                f"/api/v1/uploads/batches/{r.json()['id']}",
                headers=headers)).json()
            counts.append(detail["files"][0]["rows_extracted"])
        assert counts[0] == counts[1], f"non-deterministic extraction: {counts}"
