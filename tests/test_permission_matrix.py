"""Every API endpoint × every role.

EXPECTED lists which roles may call each endpoint. A role outside the set must
get 403; a role inside must never get 401/403 (404/422 are fine — the probe
uses placeholder ids). The table must cover every route the app exposes, so a
new endpoint cannot ship without a deliberate permission decision.
"""

import uuid

import pytest

from tests.helpers import admin, create_user, csv_file

MA, EX, MG, HR = "MASTER_ADMIN", "EXECUTIVE", "MANAGER", "HR"
ALL = {MA, EX, MG, HR}
PUBLIC = "public"

EXPECTED: dict[tuple[str, str], set[str] | str] = {
    ("GET", "/health"): PUBLIC,
    ("GET", "/health/ready"): PUBLIC,
    ("POST", "/api/v1/auth/csrf"): PUBLIC,
    ("POST", "/api/v1/auth/login"): PUBLIC,
    ("GET", "/api/v1/auth/m365/login"): PUBLIC,
    ("GET", "/api/v1/auth/m365/callback"): PUBLIC,
    ("POST", "/api/v1/auth/refresh"): PUBLIC,
    ("POST", "/api/v1/auth/logout"): PUBLIC,
    ("GET", "/api/v1/auth/me"): ALL,
    ("GET", "/api/v1/users"): {MA, EX, MG},
    ("POST", "/api/v1/users"): {MA, MG},
    ("GET", "/api/v1/users/{user_id}/profile"): ALL,
    ("PATCH", "/api/v1/users/{user_id}/status"): {MA},
    ("GET", "/api/v1/audit-logs"): {MA},
    ("GET", "/api/v1/audit-logs/export.csv"): {MA},
    ("POST", "/api/v1/uploads"): {MG},
    ("GET", "/api/v1/uploads/batches"): ALL,
    ("GET", "/api/v1/uploads/batches/{batch_id}"): ALL,
    ("GET", "/api/v1/uploads/batches/{batch_id}/review-rows"): ALL,
    ("POST", "/api/v1/uploads/batches/{batch_id}/files/{file_id}/reprocess"): {MA, EX, MG},
    ("GET", "/api/v1/uploads/batches/{batch_id}/files/{file_id}/extraction"): ALL,
    ("GET", "/api/v1/uploads/batches/{batch_id}/files/{file_id}/content"): ALL,
    ("GET", "/api/v1/employees"): ALL,
    ("GET", "/api/v1/employees/export.csv"): ALL,
    ("PATCH", "/api/v1/employees/{employee_id}"): {MG},
    ("GET", "/api/v1/employees/{employee_id}/detail"): ALL,
    ("GET", "/api/v1/employees/{employee_id}/history"): ALL,
    ("POST", "/api/v1/batches/{batch_id}/analyze"): {MG},
    ("GET", "/api/v1/batches/{batch_id}/analysis"): {MA, EX, MG},
    ("GET", "/api/v1/batches/{batch_id}/export"): ALL,
    ("POST", "/api/v1/batches/{batch_id}/export"): ALL,
    ("GET", "/api/v1/runs/{run_id}/reports/{kind}"): {MA, EX, MG},
    ("POST", "/api/v1/runs/{run_id}/resend"): {MA, EX, MG},
    ("GET", "/api/v1/dashboard/summary"): ALL,
    ("GET", "/api/v1/settings"): {MA},
    ("POST", "/api/v1/settings/purge-obsolete-data"): {MA},
    ("GET", "/api/v1/settings/m365-domains"): {MA},
    ("POST", "/api/v1/settings/m365-domains"): {MA},
    ("GET", "/api/v1/analytics/summary"): ALL,
    ("GET", "/api/v1/leaves"): ALL,
    ("POST", "/api/v1/leaves"): {MG},
    ("DELETE", "/api/v1/leaves/{leave_id}"): {MG},
}

PLACEHOLDERS = {
    "user_id": str(uuid.uuid4()), "batch_id": str(uuid.uuid4()), "file_id": str(uuid.uuid4()),
    "employee_id": str(uuid.uuid4()), "run_id": str(uuid.uuid4()), "kind": "summary.pdf", "leave_id": "999999",
}


def _app_routes() -> set[tuple[str, str]]:
    from app.main import app

    return {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}


def test_every_route_has_a_permission_decision():
    assert _app_routes() == set(EXPECTED), {
        "missing": sorted(_app_routes() - set(EXPECTED)), "stale": sorted(set(EXPECTED) - _app_routes()),
    }


async def _headers_by_role(client) -> dict[str, dict]:
    ma = await admin(client)
    _, ex = await create_user(client, ma, "pm.exec@veritrack.io", EX)
    _, mg = await create_user(client, ma, "pm.mgr@veritrack.io", MG)
    _, hr = await create_user(client, mg, "pm.hr@veritrack.io", HR)
    return {MA: ma, EX: ex, MG: mg, HR: hr}


async def _call(client, method: str, path: str, headers: dict):
    url = path.format(**PLACEHOLDERS)
    if method == "POST" and path == "/api/v1/uploads":
        return await client.post(url + "?kind=EMPLOYEE_REPO", files=[csv_file("r.csv", "Employee ID\nE-1\n")],
                                 headers=headers)
    body = {"PATCH": {}, "POST": {}}.get(method)
    return await client.request(method, url, json=body, headers=headers)


async def test_roles_are_enforced_on_every_endpoint(client, ma_user_id):
    from app.core.rate_limit import limiter, user_limiter

    roles = await _headers_by_role(client)
    failures = []
    for (method, path), allowed in sorted(EXPECTED.items()):
        if allowed == PUBLIC or path.startswith("/api/v1/auth/m365"):
            continue
        anonymous = await _call(client, method, path, {})
        if anonymous.status_code not in (401, 403):
            failures.append(f"{method} {path} anonymous -> {anonymous.status_code}")
        for role, headers in roles.items():
            limiter.reset()
            user_limiter.reset()
            code = (await _call(client, method, path, headers)).status_code
            if role in allowed and code in (401, 403):
                failures.append(f"{method} {path} {role} -> {code} (should be allowed)")
            if role not in allowed and code != 403:
                failures.append(f"{method} {path} {role} -> {code} (should be 403)")
    assert not failures, "\n".join(failures)


@pytest.fixture
async def two_managers(client, ma_user_id):
    ma = await admin(client)
    _, a = await create_user(client, ma, "pm.a@veritrack.io", MG)
    _, b = await create_user(client, ma, "pm.b@veritrack.io", MG)
    _, hr_b = await create_user(client, b, "pm.b.hr@veritrack.io", HR)
    await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO",
                      files=[csv_file("r.csv", "Employee ID,Full Name,Company Email\nE-1,Ann,ann@corp.io\n")],
                      headers=a)
    gets = (await client.post("/api/v1/uploads?kind=GETS",
                              files=[csv_file("g.csv", "Employee ID,Name,Customer Leave,Company Leave\nE-1,Ann,x,\n")],
                              headers=a)).json()
    await client.post(f"/api/v1/batches/{gets['id']}/analyze", headers=a)
    detail = (await client.get(f"/api/v1/uploads/batches/{gets['id']}", headers=a)).json()
    run_id = (await client.get(f"/api/v1/batches/{gets['id']}/analysis", headers=a)).json()["run_id"]
    employee_id = (await client.get("/api/v1/employees", headers=a)).json()["items"][0]["id"]
    await client.post("/api/v1/leaves", json={"employee_code": "E-1", "start_date": "2026-07-01"}, headers=a)
    leave_id = (await client.get("/api/v1/leaves", headers=a)).json()["items"][0]["id"]
    return {"a": a, "b": b, "hr_b": hr_b, "batch": gets["id"], "file": detail["files"][0]["id"],
            "run": run_id, "employee": employee_id, "leave": leave_id}


async def test_managers_cannot_touch_each_others_data(client, two_managers):
    d = two_managers
    probes = [
        ("GET", f"/api/v1/uploads/batches/{d['batch']}"),
        ("GET", f"/api/v1/uploads/batches/{d['batch']}/review-rows"),
        ("GET", f"/api/v1/uploads/batches/{d['batch']}/files/{d['file']}/extraction"),
        ("GET", f"/api/v1/uploads/batches/{d['batch']}/files/{d['file']}/content"),
        ("POST", f"/api/v1/uploads/batches/{d['batch']}/files/{d['file']}/reprocess"),
        ("POST", f"/api/v1/batches/{d['batch']}/analyze"),
        ("GET", f"/api/v1/batches/{d['batch']}/analysis"),
        ("GET", f"/api/v1/batches/{d['batch']}/export"),
        ("GET", f"/api/v1/runs/{d['run']}/reports/summary.pdf"),
        ("POST", f"/api/v1/runs/{d['run']}/resend"),
        ("GET", f"/api/v1/employees/{d['employee']}/detail"),
        ("GET", f"/api/v1/employees/{d['employee']}/history"),
        ("PATCH", f"/api/v1/employees/{d['employee']}"),
        ("DELETE", f"/api/v1/leaves/{d['leave']}"),
    ]
    leaks = []
    for who in ("b", "hr_b"):
        for method, url in probes:
            body = {"full_name": "Changed"} if method == "PATCH" else {} if method == "POST" else None
            r = await client.request(method, url, json=body, headers=d[who])
            if r.status_code not in (403, 404):
                leaks.append(f"{who} {method} {url} -> {r.status_code}")
    for who in ("b", "hr_b"):
        assert (await client.get("/api/v1/uploads/batches", headers=d[who])).json() == []
        assert (await client.get("/api/v1/employees", headers=d[who])).json()["total"] == 0
        assert (await client.get("/api/v1/leaves", headers=d[who])).json()["total"] == 0
    assert not leaks, "\n".join(leaks)
