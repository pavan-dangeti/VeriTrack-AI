"""End-to-end flow on deliberately messy sample data:
upload repo -> upload GETS batch (dupes/ghosts/missing columns) ->
analyze -> violations + dedup + emails + reports."""

import io

from openpyxl import load_workbook
from sqlalchemy import func, select

from app.models.analysis import ViolationResult
from tests.conftest import (
    MA_EMAIL,
    MA_PASSWORD,
)

# --- realistic messy fixtures ---------------------------------------------------

REPO_CSV = b"""Employee ID,Full Name,Company Email,Personal Email,Dept
E-100,Ann Weaver,ann.weaver@corp.io,ann.w@gmail.com,Operations
E-200,Bob Chen,,bob.chen@gmail.com,Sales
E-300,Cid Reyes,,,HR
E-400,Dia Patel,dia.patel@corp.io,,Finance
"""

# File A: violations, a no-violation, ghost employee, unreadable row
GETS_A_CSV = """EMP CODE,Emp Name,Customer Leave,Sacha Leave
E-100,Ann Weaver,✓,
E-200,Bob Chen,X,✓
E-999,Ghost Person,✓,
   ,   ,✓ ,
E-300,Cid Reyes,YES,-
"""

# File B: E-100 AGAIN (dedup case), plus E-400 violation with personal email only
GETS_B_CSV = """Employee ID,Name,Customer Leave,Sacha Leave
E-100,Ann Weaver,x,
E-400,Dia Patel,True,No
"""


async def _make_manager(client):
    login = await client.post(
        "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
    )
    ma_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = await client.post(
        "/api/v1/users",
        json={"email": "e2e.manager@veritrack.io", "role": "MANAGER"},
        headers=ma_headers,
    )
    pw = created.json()["initial_password"]
    mlogin = await client.post(
        "/api/v1/auth/login",
        json={"email": "e2e.manager@veritrack.io", "password": pw},
    )
    return {"Authorization": f"Bearer {mlogin.json()['access_token']}"}


def _csv_file(name: str, text: str):
    return ("files", (name, io.BytesIO(text.encode()), "text/csv"))


class TestEndToEnd:
    async def test_full_flow(self, client, ma_user_id):
        headers = await _make_manager(client)

        # 1. Employee repository upload
        r = await client.post(
            "/api/v1/uploads?kind=EMPLOYEE_REPO",
            files=[_csv_file("repo.csv", REPO_CSV.decode())],
            headers=headers,
        )
        assert r.status_code == 201, r.text
        repo_batch = r.json()
        assert repo_batch["status"] == "COMPLETED"  # eager celery ran inline
        assert repo_batch["processed_files"] == 1

        # 2. GETS batch upload — two messy files
        r = await client.post(
            "/api/v1/uploads?kind=GETS",
            files=[
                _csv_file("gets_a.csv", GETS_A_CSV),
                _csv_file("gets_b.csv", GETS_B_CSV),
            ],
            headers=headers,
        )
        assert r.status_code == 201, r.text
        gets_batch = r.json()
        assert gets_batch["status"] == "COMPLETED"
        assert gets_batch["total_files"] == 2

        # per-file statuses visible for polling
        detail = (await client.get(
            f"/api/v1/uploads/batches/{gets_batch['id']}", headers=headers
        )).json()
        assert all(f["status"] == "DONE" for f in detail["files"])

        # 3. Analyze
        r = await client.post(f"/api/v1/batches/{gets_batch['id']}/analyze",
                              headers=headers)
        assert r.status_code in (200, 202), r.text

        # 4. Results
        analysis = (await client.get(
            f"/api/v1/batches/{gets_batch['id']}/analysis", headers=headers
        )).json()

        totals = analysis["totals"]
        # Unique violating employees: E-100 (in both files) + E-300. E-400 has
        # Sacha='No' which parses blank BUT customer 'True' ticked → wait: rule
        # needs customer ticked AND sacha blank; 'No' is blank → VIOLATION.
        # So unique violators = E-100, E-300, E-400.
        assert totals["violations"] == 3, analysis
        assert totals["emails_sent"] == 2  # E-100 official, E-400 personal... see below
        assert totals["emails_missing"] >= 1  # E-300 has no emails at all
        assert totals["skipped"] == 2  # E-999 ghost + empty-code row

        codes = {v["employee_code"] for v in analysis["violations"]}
        assert codes == {"E-100", "E-300", "E-400"}

        by_code = {v["employee_code"]: v for v in analysis["violations"]}
        assert by_code["E-100"]["email_to"] == "ann.weaver@corp.io"
        assert by_code["E-100"]["email_status"] == "SENT"
        assert by_code["E-400"]["email_to"] == "dia.patel@corp.io"  # official present
        assert by_code["E-300"]["email_status"] == "SKIPPED_NO_EMAIL"

        # skipped rows carry reasons
        skip_statuses = {s["status"] for s in analysis["skipped_rows"]}
        assert "NOT_IN_REPO" in skip_statuses

        # DB-level dedup guarantee
        async with __import__("tests.conftest", fromlist=["test_session"]).test_session() as db:
            count = (await db.execute(
                select(func.count()).select_from(ViolationResult)
            )).scalar_one()
        assert count == 3

    async def test_reports_generated_and_downloadable(self, client, ma_user_id):
        headers = await _make_manager(client)
        await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO",
                          files=[_csv_file("repo.csv", REPO_CSV.decode())],
                          headers=headers)
        r = await client.post("/api/v1/uploads?kind=GETS",
                              files=[_csv_file("g.csv", GETS_A_CSV)],
                              headers=headers)
        batch_id = r.json()["id"]
        await client.post(f"/api/v1/batches/{batch_id}/analyze", headers=headers)

        # Manager downloads both reports
        pdf = await client.get(f"/api/v1/runs-batch/{batch_id}/reports/summary.pdf",
                               headers=headers)
        xlsx = await client.get(f"/api/v1/runs-batch/{batch_id}/reports/3tab.xlsx",
                                headers=headers)
        # route is /runs/{run_id}/reports/... but we don't know run id here;
        # fetch analysis first
        analysis = (await client.get(
            f"/api/v1/batches/{batch_id}/analysis", headers=headers)).json()
        run_id = analysis["run_id"]
        pdf = await client.get(f"/api/v1/runs/{run_id}/reports/summary.pdf",
                               headers=headers)
        xlsx = await client.get(f"/api/v1/runs/{run_id}/reports/3tab.xlsx",
                                headers=headers)
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"

        wb = load_workbook(io.BytesIO(xlsx.content))
        assert wb.sheetnames == ["Sent", "Violations-No-Email", "Skipped-Not-Processed"]

        # Executive can view the same analysis + reports (mirrored visibility)
        elogin = None
        ma_login = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD})
        ma_h = {"Authorization": f"Bearer {ma_login.json()['access_token']}"}
        exec_created = await client.post(
            "/api/v1/users",
            json={"email": "view.exec@veritrack.io", "role": "EXECUTIVE"},
            headers=ma_h)
        epw = exec_created.json()["initial_password"]
        elogin = await client.post(
            "/api/v1/auth/login",
            json={"email": "view.exec@veritrack.io", "password": epw})
        e_headers = {"Authorization": f"Bearer {elogin.json()['access_token']}"}

        seen = await client.get(f"/api/v1/batches/{batch_id}/analysis", headers=e_headers)
        assert seen.status_code == 200
        dl = await client.get(f"/api/v1/runs/{run_id}/reports/summary.pdf", headers=e_headers)
        assert dl.status_code == 200


class TestUploadValidation:
    async def test_rejects_disguised_file(self, client, ma_user_id):
        headers = await _make_manager(client)
        evil = ("files", ("data.csv", io.BytesIO(bytes(range(256)) * 8), "text/csv"))
        r = await client.post("/api/v1/uploads?kind=GETS", files=[evil], headers=headers)
        assert r.status_code == 415

    async def test_rejects_more_than_max(self, client, ma_user_id):
        from app.core.config import settings

        headers = await _make_manager(client)
        files = [_csv_file(f"f{i}.csv", "a,b\n1,2\n")
                 for i in range(settings.max_files_per_batch + 1)]
        r = await client.post("/api/v1/uploads?kind=GETS", files=files, headers=headers)
        assert r.status_code == 400

    async def test_ma_cannot_upload(self, client, ma_user_id):
        login = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}
        r = await client.post("/api/v1/uploads?kind=GETS",
                              files=[_csv_file("a.csv", "a,b\n1,2\n")], headers=h)
        assert r.status_code == 403  # view-only per permission matrix


class TestExports:
    async def _prepared(self, client):
        headers = await _make_manager(client)
        await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO",
                          files=[_csv_file("repo.csv", REPO_CSV.decode())],
                          headers=headers)
        r = await client.post("/api/v1/uploads?kind=GETS",
                              files=[_csv_file("g.csv", GETS_A_CSV)],
                              headers=headers)
        return headers, r.json()["id"]

    async def test_all_four_formats(self, client, ma_user_id):
        headers, batch_id = await self._prepared(client)
        expectations = {
            "csv": b"employee_code",
            "xlsx": b"PK",
            "pdf": b"%PDF",
            "png": b"\x89PNG",
        }
        for fmt, magic in expectations.items():
            r = await client.post(
                f"/api/v1/batches/{batch_id}/export",
                json={"format": fmt},
                headers=headers,
            )
            assert r.status_code == 200, (fmt, r.text[:200])
            ok = (
                magic in r.content if magic.startswith(b"employee") else r.content.startswith(magic)
            )
            assert ok, fmt

    async def test_column_filtering(self, client, ma_user_id):
        headers, batch_id = await self._prepared(client)
        r = await client.post(
            f"/api/v1/batches/{batch_id}/export",
            json={"format": "csv", "columns": ["employee_code", "full_name"]},
            headers=headers,
        )
        lines = [ln for ln in r.text.strip().splitlines() if ln]
        assert lines[0] == "employee_code,full_name"
        assert len(lines) >= 2
