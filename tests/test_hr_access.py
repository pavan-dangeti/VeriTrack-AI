"""HR read-only scoping: can see + download own manager's GETS sheets, never
anything mutating, never another manager's data. Also locks the review-flag
fields that /employees must serialize (locked requirement 3a)."""

import io
import uuid

from sqlalchemy import select

from app.models.uploads import ExtractedRow, UploadedFile
from tests.conftest import (
    MA_EMAIL,
    MA_PASSWORD,
    auth_headers,
    login_access_token,
    test_session,
)

REPO_CSV = b"""Employee ID,Full Name,Company Email,Personal Email,Dept
E-100,Ann Weaver,ann.weaver@corp.io,ann.w@gmail.com,Operations
"""
GETS_CSV = """EMP CODE,Emp Name,Customer Leave,Sacha Leave
E-100,Ann Weaver,✓,
"""


def _csv(name: str, text: str):
    return ("files", (name, io.BytesIO(text.encode()), "text/csv"))


async def _make_manager(client, email="mgr@veritrack.io"):
    ma_headers = auth_headers(
        await login_access_token(client, MA_EMAIL, MA_PASSWORD)
    )
    created = await client.post(
        "/api/v1/users",
        json={"email": email, "role": "MANAGER"},
        headers=ma_headers,
    )
    assert created.status_code == 201, created.text
    return auth_headers(
        await login_access_token(client, email, created.json()["initial_password"])
    )


async def _make_hr(client, manager_headers, email="hr@veritrack.io"):
    created = await client.post(
        "/api/v1/users", json={"email": email, "role": "HR"}, headers=manager_headers
    )
    assert created.status_code == 201, created.text
    return auth_headers(
        await login_access_token(client, email, created.json()["initial_password"])
    )


async def _prepared(client, email="mgr@veritrack.io"):
    m = await _make_manager(client, email=email)
    await client.post(
        "/api/v1/uploads?kind=EMPLOYEE_REPO",
        files=[_csv("repo.csv", REPO_CSV.decode())],
        headers=m,
    )
    r = await client.post(
        "/api/v1/uploads?kind=GETS", files=[_csv("g.csv", GETS_CSV)], headers=m
    )
    return m, r.json()["id"]


async def test_hr_sees_own_managers_batches_and_can_download(client, ma_user_id):
    m, batch_id = await _prepared(client)
    hr = await _make_hr(client, m)

    lst = await client.get("/api/v1/uploads/batches", headers=hr)
    assert lst.status_code == 200, lst.text
    assert batch_id in {b["id"] for b in lst.json()}

    # HR can download the XLSX export of their manager's GETS batch (read-only)
    dl = await client.get(f"/api/v1/batches/{batch_id}/export?format=xlsx", headers=hr)
    assert dl.status_code == 200, dl.text[:200]
    assert dl.content.startswith(b"PK")

    # ...but cannot trigger analyze (mutating)
    an = await client.post(f"/api/v1/batches/{batch_id}/analyze", headers=hr)
    assert an.status_code == 403


async def test_hr_cannot_see_another_managers_batch(client, ma_user_id):
    m1, _ = await _prepared(client)
    m2, batch2 = await _prepared(client, email="mgr2@veritrack.io")
    hr1 = await _make_hr(client, m1)

    lst = await client.get("/api/v1/uploads/batches", headers=hr1)
    assert batch2 not in {b["id"] for b in lst.json()}

    dl = await client.get(f"/api/v1/batches/{batch2}/export?format=xlsx", headers=hr1)
    assert dl.status_code == 403


async def test_review_rows_endpoint_returns_flagged_reason(client, ma_user_id):
    m, batch_id = await _prepared(client)
    hr = await _make_hr(client, m)

    # Deterministic flag: insert one ExtractedRow needing review for this batch.
    async with test_session() as db:
        file = (
            await db.execute(
                select(UploadedFile).where(UploadedFile.batch_id == uuid.UUID(batch_id))
            )
        ).scalars().first()
        db.add(
            ExtractedRow(
                file_id=file.id,
                row_index=0,
                data={"employee_code": "e-100", "full_name": "Ann Weaver"},
                confidence=0.58,
                needs_review=True,
                review_note="Low OCR confidence: 58%",
            )
        )
        await db.commit()

    r = await client.get(f"/api/v1/uploads/batches/{batch_id}/review-rows", headers=hr)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["review_note"] == "Low OCR confidence: 58%"
    assert items[0]["confidence"] == 0.58
    assert items[0]["data"]["employee_code"] == "e-100"


async def test_employees_list_serializes_review_fields(client, ma_user_id):
    m, _ = await _prepared(client)
    r = await client.get("/api/v1/employees", headers=m)
    assert r.status_code == 200
    emp = r.json()["items"][0]
    assert emp["needs_review"] is False
    assert emp["review_note"] is None
    assert "ocr_confidence" in emp