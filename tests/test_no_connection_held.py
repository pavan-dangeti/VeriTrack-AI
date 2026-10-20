"""No database connection is held while a request or job does slow work: storage reads and writes, building
reports and exports. Held connections starve the pool under load; the 200-user load test hit pool
timeouts (HTTP 500) until uploads, report generation, exports and downloads released theirs first.

Each slow call records how many pooled connections are checked out at that moment; with one request at a
time, that must be none.
"""

import pytest

from app.db.session import engine
from app.services import exporters, reporting
from app.services.storage import LocalDiskBackend
from tests.helpers import csv_file, manager

REPO = "Employee ID,Full Name,Company Email\nE-1,Ann,ann@corp.io\n"
SHEET = "Employee ID,Name,Customer Leave,Company Leave\nE-1,Ann,x,\n"


@pytest.fixture
def held(monkeypatch) -> dict[str, list[int]]:
    seen: dict[str, list[int]] = {}

    def watch(owner, name, label):
        real = getattr(owner, name)

        def watched(*args, **kwargs):
            seen.setdefault(label, []).append(engine.pool.checkedout())
            return real(*args, **kwargs)

        monkeypatch.setattr(owner, name, watched)

    watch(LocalDiskBackend, "put", "storage write")
    watch(LocalDiskBackend, "get_bytes", "storage read")
    watch(reporting, "build_excel_3tab", "excel report")
    watch(reporting, "build_summary_pdf", "pdf report")
    for fmt, (content_type, filename, exporter) in list(exporters.EXPORTERS.items()):
        def tracked(*a, _real=exporter, **k):
            seen.setdefault("export", []).append(engine.pool.checkedout())
            return _real(*a, **k)

        monkeypatch.setitem(exporters.EXPORTERS, fmt, (content_type, filename, tracked))
    return seen


async def test_slow_work_holds_no_connection(client, ma_user_id, held):
    h = await manager(client, "pool")
    await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO", files=[csv_file("r.csv", REPO)], headers=h)
    batch = (await client.post("/api/v1/uploads?kind=TIMESHEET", files=[csv_file("s.csv", SHEET)],
                               headers=h)).json()   # inline mode: stored, read and processed here
    assert (await client.post(f"/api/v1/batches/{batch['id']}/analyze", headers=h)).status_code in (200, 202)
    run_id = (await client.get(f"/api/v1/batches/{batch['id']}/analysis", headers=h)).json()["run_id"]
    file_id = (await client.get(f"/api/v1/uploads/batches/{batch['id']}", headers=h)).json()["files"][0]["id"]
    for url in (f"/api/v1/batches/{batch['id']}/export", f"/api/v1/runs/{run_id}/reports/summary.pdf",
                f"/api/v1/uploads/batches/{batch['id']}/files/{file_id}/content"):
        assert (await client.get(url, headers=h)).status_code == 200, url

    assert set(held) == {"storage write", "storage read", "excel report", "pdf report", "export"}, held
    assert {label: max(counts) for label, counts in held.items()} == dict.fromkeys(held, 0), held
