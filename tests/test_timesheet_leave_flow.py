"""End-to-end: GETS screenshots -> verified extraction -> leave rule, on the synthetic sheets.

Analysis must flag exactly the employees whose GETS leave is missing from the register.
"""

import io
import json

import pytest

from scripts.gen_synthetic_gets import ensure
from tests.conftest import MA_EMAIL, MA_PASSWORD

DATA = ensure()
if DATA is None:
    pytest.skip("synthetic GETS sheets need Playwright + Chromium", allow_module_level=True)
TRUTH = json.loads((DATA / "ground_truth.json").read_text())
SHEETS = {
    "synthetic_000.png": "103729",  # Mar 2026, OOO 9, 24
    "synthetic_004.png": "158082",  # Sep 2027, no Out Of Office row
    "synthetic_007.png": "141220",  # Jul 2025, OOO 1, 3, 14, 28
    "synthetic_013.png": "197061",  # Jun 2025, OOO 2, 3, 11, 18
}

REPO_CSV = b"""Employee ID,Full Name,Company Email,Personal Email,Dept
103729,Golf Anonymous,golf.anonymous@example.com,,Eng
158082,Kilo Specimen,kilo.specimen@example.com,,Eng
141220,Bravo Example,,bravo.example@example.net,Eng
197061,Echo Specimen,echo.specimen@example.com,,Eng
"""

# 103729: both OOO days recorded            -> compliant
# 141220: 1, 3, 14 recorded, 28 missing      -> violation (2025-07-28)
# 197061: range 2-3 and 11 recorded, 18 missing -> violation (2025-06-18)
# 158082: no Out Of Office row              -> compliant
LEAVE_CSV = b"""Employee ID,From Date,To Date,Leave Type
103729,09-03-2026,,Casual
103729,2026-03-24,,Casual
141220,01/07/2025,01/07/2025,Sick
141220,03-Jul-2025,,Casual
141220,2025-07-14,,Casual
197061,02-Jun-2025,03-Jun-2025,Earned
197061,11/06/2025,,Casual
"""


def _engine_ready() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


async def _manager(client, tag: str) -> dict:
    login = await client.post("/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD})
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = await client.post(
        "/api/v1/users", json={"email": f"{tag}@veritrack.io", "role": "MANAGER"}, headers=h
    )
    m = await client.post(
        "/api/v1/auth/login",
        json={"email": f"{tag}@veritrack.io", "password": created.json()["initial_password"]},
    )
    return {"Authorization": f"Bearer {m.json()['access_token']}"}


@pytest.fixture
def real_ocr(monkeypatch):
    if not _engine_ready():
        pytest.skip("RapidOCR not installed")
    from app.core.config import settings
    from app.services.extraction.ocr import reset_ocr_engine_for_tests

    monkeypatch.setattr(settings, "ocr_engine", "rapid")
    reset_ocr_engine_for_tests()
    yield
    reset_ocr_engine_for_tests()


class TestTimesheetLeaveFlow:
    async def test_full_flow_flags_only_missing_register_leave(self, client, ma_user_id, real_ocr):
        h = await _manager(client, "ts.flow")
        r = await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO",
                              files=[("files", ("repo.csv", io.BytesIO(REPO_CSV), "text/csv"))],
                              headers=h)
        assert r.status_code == 201 and r.json()["status"] == "COMPLETED"

        r = await client.post("/api/v1/uploads?kind=COMPANY_LEAVE",
                              files=[("files", ("leave.csv", io.BytesIO(LEAVE_CSV), "text/csv"))],
                              headers=h)
        assert r.status_code == 201, r.text
        june = (await client.get("/api/v1/leaves?month=2025-06", headers=h)).json()
        assert june["total"] == 3  # range 2-3 expanded + 11
        july = (await client.get("/api/v1/leaves?month=2025-07", headers=h)).json()
        assert july["total"] == 3

        files = [("files", (name, io.BytesIO((DATA / name).read_bytes()), "image/png"))
                 for name in SHEETS]
        r = await client.post("/api/v1/uploads?kind=GETS", files=files, headers=h)
        assert r.status_code == 201, r.text
        batch_id = r.json()["id"]
        detail = (await client.get(f"/api/v1/uploads/batches/{batch_id}", headers=h)).json()
        assert detail["status"] == "COMPLETED"
        for f in detail["files"]:
            assert f["status"] == "DONE", f
            assert f["sheet_status"] in ("VERIFIED", "CORRECTED"), f
            t = TRUTH[f["original_filename"]]
            assert f["sheet_period"] == f"{t['year']}-{t['month']:02d}"
            assert f["needs_review_count"] == 0

        r = await client.post(f"/api/v1/batches/{batch_id}/analyze", headers=h)
        assert r.status_code == 202, r.text
        assert r.json()["violations"] == 2
        analysis = (await client.get(f"/api/v1/batches/{batch_id}/analysis", headers=h)).json()
        flagged = {v["employee_code"]: v for v in analysis["violations"]}
        assert set(flagged) == {"141220", "197061"}, flagged
        assert flagged["141220"]["details"]["missing_in_register"] == ["2025-07-28"]
        assert flagged["197061"]["details"]["missing_in_register"] == ["2025-06-18"]
        assert flagged["141220"]["email_to"] == "bravo.example@example.net"  # personal fallback
        assert analysis["totals"]["matched"] == 4
        assert analysis["totals"]["violations"] == 2

    async def test_extraction_endpoint_exposes_verified_grid(self, client, ma_user_id, real_ocr):
        h = await _manager(client, "ts.grid")
        png = (DATA / "synthetic_002.png").read_bytes()
        r = await client.post("/api/v1/uploads?kind=GETS",
                              files=[("files", ("s.png", io.BytesIO(png), "image/png"))], headers=h)
        batch = r.json()
        detail = (await client.get(f"/api/v1/uploads/batches/{batch['id']}", headers=h)).json()
        fid = detail["files"][0]["id"]
        ext = (await client.get(f"/api/v1/uploads/batches/{batch['id']}/files/{fid}/extraction",
                                headers=h)).json()
        sheet = ext["meta"]["gets_sheets"][0]
        assert sheet["verified"] is True
        truth = TRUTH["synthetic_002.png"]
        assert sheet["employee_name"] == truth["employee_name"]
        assert len(ext["rows"]) == len(truth["lines"])
        first = next(r for r in ext["rows"] if r["data"]["extra"]["project_name"] == "Alpha")
        assert first["data"]["extra"]["total"] == 34
        assert set(first["data"]["extra"]["day_status"].values()) == {"LM_APPROVED"}
        content = await client.get(f"/api/v1/uploads/batches/{batch['id']}/files/{fid}/content",
                                   headers=h)
        assert content.status_code == 200 and content.content == png

    async def test_gets_export_has_all_day_columns(self, client, ma_user_id, real_ocr):
        h = await _manager(client, "ts.export")
        png = (DATA / "synthetic_000.png").read_bytes()  # March: 31 days
        r = await client.post("/api/v1/uploads?kind=GETS",
                              files=[("files", ("s.png", io.BytesIO(png), "image/png"))], headers=h)
        exp = await client.get(f"/api/v1/batches/{r.json()['id']}/export?format=csv", headers=h)
        assert exp.status_code == 200
        header = [c.strip().strip('"') for c in exp.text.splitlines()[0].split(",")]
        assert [c for c in header if c.startswith("day_")] == [f"day_{d:02d}" for d in range(1, 32)]
        assert "total" in header and "hour_type" in header
