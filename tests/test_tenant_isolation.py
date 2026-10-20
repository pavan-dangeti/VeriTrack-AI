"""Organisations are isolated from each other, on every endpoint and in the database itself.

Organisation A (the bootstrap one) holds data in every table. Organisation B's four roles then attack it
through every route the app exposes: each route is classified below, and the classification must cover the
whole API, so a new endpoint cannot ship without a cross-organisation check. Every attack is paired with a
check that A's data still exists and A's owner can still reach it, so a 404 cannot come from missing data.

The database tests check the second layer on its own: row-level security, with no application filter.
"""

import asyncio
import contextvars

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app.core.config import settings
from app.db.tenant import SYSTEM, tenant
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import open_session
from tests.helpers import admin, create_user, csv_file, login
from tests.test_permission_matrix import EX, EXPECTED, HR, MA, MG, PUBLIC

A_REPO = "Employee ID,Full Name,Company Email\nA-100,Alice Alpha,alice@alpha-corp.io\n"
A_SHEET = "Employee ID,Name,Customer Leave,Company Leave\nA-100,Alice Alpha,x,\n"
B_REPO = "Employee ID,Full Name,Company Email\nB-200,Bob Beta,bob@beta-corp.io\n"

# a route's path carries one of A's ids: B must get 404 (or 403 where its role may not call the route)
PROBE = "probe"
# a list, summary or export: B's response must contain nothing of A's
LIST = "list"
# creates or deletes: checked one by one in test_writes_stay_inside_the_organisation
WRITE = "write"
COVERAGE: dict[tuple[str, str], str] = {
    **{route: PUBLIC for route, allowed in EXPECTED.items() if allowed == PUBLIC},
    ("GET", "/api/v1/auth/me"): LIST,
    ("GET", "/api/v1/users"): LIST,
    ("POST", "/api/v1/users"): WRITE,
    ("GET", "/api/v1/users/{user_id}/profile"): PROBE,
    ("PATCH", "/api/v1/users/{user_id}/status"): PROBE,
    ("GET", "/api/v1/audit-logs"): LIST,
    ("GET", "/api/v1/audit-logs/export.csv"): LIST,
    ("GET", "/api/v1/audit-logs/verify"): LIST,
    ("POST", "/api/v1/uploads"): WRITE,
    ("GET", "/api/v1/uploads/batches"): LIST,
    ("GET", "/api/v1/uploads/batches/{batch_id}"): PROBE,
    ("GET", "/api/v1/uploads/batches/{batch_id}/review-rows"): PROBE,
    ("POST", "/api/v1/uploads/batches/{batch_id}/files/{file_id}/reprocess"): PROBE,
    ("GET", "/api/v1/uploads/batches/{batch_id}/files/{file_id}/extraction"): PROBE,
    ("GET", "/api/v1/uploads/batches/{batch_id}/files/{file_id}/content"): PROBE,
    ("GET", "/api/v1/employees"): LIST,
    ("GET", "/api/v1/employees/export.csv"): LIST,
    ("PATCH", "/api/v1/employees/{employee_id}"): PROBE,
    ("GET", "/api/v1/employees/{employee_id}/detail"): PROBE,
    ("GET", "/api/v1/employees/{employee_id}/history"): PROBE,
    ("POST", "/api/v1/batches/{batch_id}/analyze"): PROBE,
    ("GET", "/api/v1/batches/{batch_id}/analysis"): PROBE,
    ("GET", "/api/v1/batches/{batch_id}/export"): PROBE,
    ("POST", "/api/v1/batches/{batch_id}/export"): PROBE,
    ("GET", "/api/v1/runs/{run_id}/reports/{kind}"): PROBE,
    ("POST", "/api/v1/runs/{run_id}/resend"): PROBE,
    ("GET", "/api/v1/dashboard/summary"): LIST,
    ("GET", "/api/v1/settings"): LIST,
    ("POST", "/api/v1/settings/purge-obsolete-data"): WRITE,
    ("GET", "/api/v1/settings/m365-domains"): LIST,
    ("POST", "/api/v1/settings/m365-domains"): WRITE,
    ("GET", "/api/v1/analytics/summary"): LIST,
    ("GET", "/api/v1/leaves"): LIST,
    ("POST", "/api/v1/leaves"): WRITE,
    ("DELETE", "/api/v1/leaves/{leave_id}"): PROBE,
}
# summaries hold counts, not names: B's must not change when A adds data
SUMMARIES = ("/api/v1/dashboard/summary", "/api/v1/analytics/summary")


def test_every_route_has_a_cross_organisation_check():
    from app.main import app

    routes = {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}
    assert routes == set(COVERAGE), {
        "missing": sorted(routes - set(COVERAGE)), "stale": sorted(set(COVERAGE) - routes),
    }


async def _org_b(client) -> dict:
    from app.cli import create_organization

    rc, password = await create_organization("Beta Org", "admin@beta.example")
    assert rc == 0 and password
    ma = await login(client, "admin@beta.example", password)
    _, ex = await create_user(client, ma, "b.exec@beta.example", EX)
    _, mg = await create_user(client, ma, "b.mgr@beta.example", MG)
    _, hr = await create_user(client, mg, "b.hr@beta.example", HR)
    r = await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO", files=[csv_file("beta-repo.csv", B_REPO)],
                          headers=mg)
    assert r.status_code in (200, 201, 202), r.text
    return {MA: ma, EX: ex, MG: mg, HR: hr}


async def _org_a(client) -> dict:
    ma = await admin(client)
    _, ex = await create_user(client, ma, "a.exec@alpha.example", EX)
    mgr_id, mg = await create_user(client, ma, "a.mgr@alpha.example", MG)
    _, hr = await create_user(client, mg, "a.hr@alpha.example", HR)
    await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO", files=[csv_file("alpha-repo.csv", A_REPO)],
                      headers=mg)
    batch = (await client.post("/api/v1/uploads?kind=TIMESHEET", files=[csv_file("alpha-sheet.csv", A_SHEET)],
                               headers=mg)).json()
    assert (await client.post(f"/api/v1/batches/{batch['id']}/analyze", headers=mg)).status_code in (200, 202)
    detail = (await client.get(f"/api/v1/uploads/batches/{batch['id']}", headers=mg)).json()
    run_id = (await client.get(f"/api/v1/batches/{batch['id']}/analysis", headers=mg)).json()["run_id"]
    employee_id = (await client.get("/api/v1/employees", headers=mg)).json()["items"][0]["id"]
    await client.post("/api/v1/leaves", json={"employee_code": "A-100", "start_date": "2026-07-01"}, headers=mg)
    leave_id = (await client.get("/api/v1/leaves", headers=mg)).json()["items"][0]["id"]
    assert (await client.post("/api/v1/settings/m365-domains", json={"domain": "alpha-corp.io"},
                              headers=ma)).status_code == 201
    ids = {"user_id": mgr_id, "batch_id": batch["id"], "file_id": detail["files"][0]["id"], "run_id": run_id,
           "employee_id": employee_id, "leave_id": str(leave_id), "kind": "summary.pdf"}
    # anything that identifies A's data, as it would appear in a response
    markers = ["A-100", "Alice Alpha", "alice@alpha-corp.io", "alpha-corp.io", "alpha-repo.csv",
               "alpha-sheet.csv", "@alpha.example", "ma@veritrack.io",
               *(v for k, v in ids.items() if k not in ("kind", "leave_id"))]
    return {MA: ma, EX: ex, MG: mg, HR: hr, "ids": ids, "markers": markers}


@pytest.fixture
async def orgs(client, ma_user_id):
    b = await _org_b(client)
    before = {(role, path): (await client.get(path, headers=b[role])).json()
              for role in (MA, EX, MG, HR) for path in SUMMARIES}
    a = await _org_a(client)
    return {"a": a, "b": b, "summaries_before": before}


def _reset_limits():
    from app.core.rate_limit import limiter, user_limiter

    limiter.reset()
    user_limiter.reset()


async def _a_can_still_reach_everything(client, a):
    """The owner's view after the attacks: every resource is there and unchanged."""
    ids = a["ids"]
    for path in ("/api/v1/uploads/batches/{batch_id}", "/api/v1/uploads/batches/{batch_id}/review-rows",
                 "/api/v1/uploads/batches/{batch_id}/files/{file_id}/extraction",
                 "/api/v1/uploads/batches/{batch_id}/files/{file_id}/content",
                 "/api/v1/batches/{batch_id}/analysis", "/api/v1/batches/{batch_id}/export",
                 "/api/v1/runs/{run_id}/reports/{kind}", "/api/v1/employees/{employee_id}/history",
                 "/api/v1/users/{user_id}/profile"):
        _reset_limits()
        r = await client.get(path.format(**ids), headers=a[MG])
        assert r.status_code == 200, f"A's own {path} -> {r.status_code}"
    detail = (await client.get(f"/api/v1/employees/{ids['employee_id']}/detail", headers=a[MG])).json()
    assert "Alice Alpha" in str(detail)
    assert [str(i["id"]) for i in (await client.get("/api/v1/leaves", headers=a[MG])).json()["items"]] == [
        ids["leave_id"]]
    assert (await client.get("/api/v1/auth/me", headers=a[MG])).status_code == 200   # still active


async def test_other_organisation_ids_are_not_found(client, orgs):
    a, b = orgs["a"], orgs["b"]
    leaks = []
    for (method, path), kind in sorted(COVERAGE.items()):
        if kind != PROBE:
            continue
        url = path.format(**a["ids"])
        body = {"PATCH": {"full_name": "Changed", "is_active": False}, "POST": {}}.get(method)
        for role in (MA, EX, MG, HR):
            _reset_limits()
            code = (await client.request(method, url, json=body, headers=b[role])).status_code
            expected = 404 if role in EXPECTED[(method, path)] else 403
            if code != expected:
                leaks.append(f"B's {role} {method} {path} -> {code}, expected {expected}")
    assert not leaks, "\n".join(leaks)
    await _a_can_still_reach_everything(client, a)


async def test_lists_and_exports_show_nothing_of_another_organisation(client, orgs):
    a, b = orgs["a"], orgs["b"]
    leaks = []
    for (method, path), kind in sorted(COVERAGE.items()):
        if kind != LIST:
            continue
        for role in (MA, EX, MG, HR):
            if role not in EXPECTED[(method, path)]:
                continue
            _reset_limits()
            r = await client.get(path, headers=b[role])
            if r.status_code != 200:
                leaks.append(f"B's {role} {path} -> {r.status_code}")
            leaks += [f"B's {role} {path} shows {m!r}" for m in a["markers"] if m in r.text]
            if path in SUMMARIES and r.json() != orgs["summaries_before"][(role, path)]:
                leaks.append(f"B's {role} {path} changed when A added data")
    assert not leaks, "\n".join(leaks)
    # and A sees its own data through the same routes (the markers are real)
    assert "Alice Alpha" in (await client.get("/api/v1/employees", headers=a[MG])).text
    assert "a.mgr@alpha.example" in (await client.get("/api/v1/users", headers=a[MA])).text


async def test_writes_stay_inside_the_organisation(client, orgs, monkeypatch):
    a, b = orgs["a"], orgs["b"]

    # an upload reusing A's employee code creates B's own record and leaves A's alone
    r = await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO",
                          files=[csv_file("b2.csv", "Employee ID,Full Name\nA-100,Mallory\n")], headers=b[MG])
    assert r.status_code in (200, 201, 202), r.text
    assert "Mallory" in (await client.get("/api/v1/employees", headers=b[MG])).text
    assert "Mallory" not in (await client.get("/api/v1/employees", headers=a[MG])).text

    # a new user is created in the creator's organisation
    await create_user(client, b[MA], "b.exec2@beta.example", EX)
    with tenant(SYSTEM):
        async with open_session() as db:
            orgs_of = dict((await db.execute(select(User.email, User.org_id).where(
                User.email.in_(["b.exec2@beta.example", "admin@beta.example"])))).all())
    assert orgs_of["b.exec2@beta.example"] == orgs_of["admin@beta.example"]

    # e-mail is a global sign-in identity: one already used in A is refused, and A's account is untouched
    r = await client.post("/api/v1/users", json={"email": "a.exec@alpha.example", "role": EX}, headers=b[MA])
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"

    # a leave for A's employee code lands in B's register only
    r = await client.post("/api/v1/leaves", json={"employee_code": "A-100", "start_date": "2026-07-02"},
                          headers=b[MG])
    assert r.status_code == 201, r.text
    assert (await client.get("/api/v1/leaves", headers=a[MG])).json()["total"] == 1

    # a domain belongs to one organisation
    r = await client.post("/api/v1/settings/m365-domains", json={"domain": "alpha-corp.io"}, headers=b[MA])
    assert r.status_code == 409 and r.json()["error"]["code"] == "domain_taken"
    assert (await client.get("/api/v1/settings/m365-domains", headers=b[MA])).json()["items"] == []

    # purging with a zero-day retention window removes nothing of A's
    monkeypatch.setattr(settings, "retention_days", 0)
    assert (await client.post("/api/v1/settings/purge-obsolete-data", headers=b[MA])).status_code == 200

    await _a_can_still_reach_everything(client, a)


async def test_m365_sign_in_needs_the_domains_organisation(client, orgs, monkeypatch):
    """alpha-corp.io is approved by A; an account with that e-mail in B must not sign in through it."""
    from app.services import m365_service

    a, b = orgs["a"], orgs["b"]
    await create_user(client, b[MA], "eve@alpha-corp.io", EX)
    await create_user(client, a[MA], "carol@alpha-corp.io", EX)
    monkeypatch.setattr(settings, "m365_client_id", "id")
    monkeypatch.setattr(settings, "m365_client_secret", "secret")

    async def exchange(code, verifier):
        return code

    monkeypatch.setattr(m365_service, "exchange_code", exchange)
    monkeypatch.setattr(m365_service, "validate_id_token", lambda token, expected_nonce=None: {"email": token})

    async def sign_in(email):
        _reset_limits()
        client.cookies.update({"veritrack_sso_state": "s", "veritrack_sso_nonce": "n",
                               "veritrack_sso_verifier": "v"})
        return await client.get("/api/v1/auth/m365/callback", params={"state": "s", "code": email})

    assert (await sign_in("carol@alpha-corp.io")).status_code == 200
    r = await sign_in("eve@alpha-corp.io")
    assert r.status_code == 403 and r.json()["error"]["code"] == "account_unavailable"


async def test_a_job_with_no_request_context_runs_in_its_batchs_organisation(client, orgs):
    """A Celery worker or restart recovery has no request: the job must find its organisation itself."""
    from app.models.uploads import BatchKind
    from app.services import jobs
    from app.services.batch_service import create_batch

    with tenant(SYSTEM):
        async with open_session() as db:
            org_b = (await db.execute(select(Organization.id).where(Organization.name == "Beta Org"))).scalar_one()
            b_manager = (await db.execute(select(User).where(User.email == "b.mgr@beta.example"))).scalar_one()
    with tenant(org_b):
        async with open_session() as db:
            batch = await create_batch(db, manager=b_manager, kind=BatchKind.EMPLOYEE_REPO,
                                       files=[("late.csv", b"Employee ID,Full Name\nB-300,Late Arrival\n")])
    result = await asyncio.get_running_loop().create_task(
        jobs._process_batch_job(str(batch.id)), context=contextvars.Context())
    assert result.get("status") != "error", result
    assert "Late Arrival" in (await client.get("/api/v1/employees", headers=orgs["b"][MG])).text
    assert "Late Arrival" not in (await client.get("/api/v1/employees", headers=orgs["a"][MG])).text


# ---- the database layer on its own ----

async def _tenant_tables() -> list[str]:
    """Table names from the catalogue (never user input), interpolated into the SQL below."""
    with tenant(SYSTEM):
        return await _catalogue_tables()


async def _catalogue_tables() -> list[str]:
    async with open_session() as db:
        return list((await db.execute(text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'org_id' ORDER BY table_name"
        ))).scalars())


async def test_application_transactions_run_as_a_role_that_cannot_bypass_row_level_security():
    """A superuser or BYPASSRLS role ignores every policy. Whatever role the app logs in as (CI's is a
    superuser), each transaction switches to veritrack_app, which can do neither."""
    async with open_session() as db:
        role, bypass = (await db.execute(text(
            "SELECT current_user, rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"))).one()
    assert (role, bypass) == ("veritrack_app", False)


async def test_every_tenant_table_has_forced_row_level_security():
    tables = await _tenant_tables()
    assert len(tables) >= 12
    async with open_session() as db:
        rows = dict((await db.execute(text(
            "SELECT c.relname, c.relrowsecurity AND c.relforcerowsecurity AND EXISTS "
            "(SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid) "
            "FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'"))).all())
    unprotected = [t for t in [*tables, "organizations"] if not rows.get(t)]
    assert not unprotected


async def test_row_level_security_alone_hides_and_blocks_other_organisations_rows(client, orgs):
    """Raw SQL with no WHERE clause: what each tenant can see and write, by table."""
    tables = await _tenant_tables()
    with tenant(SYSTEM):   # the true row counts
        async with open_session() as db:
            org_ids = list((await db.execute(select(Organization.id))).scalars())
            truth = {(t, o): (await db.execute(text(f"SELECT count(*) FROM {t} WHERE org_id = :o"), {"o": o}))  # noqa: S608
                     .scalar_one() for t in tables for o in org_ids}
    assert len(org_ids) == 2
    populated = {t for (t, o), n in truth.items() if n}
    assert len(populated) >= 10, f"only {sorted(populated)} hold data; the check would prove little"

    wrong = []
    for org in org_ids:
        other = next(o for o in org_ids if o != org)
        with tenant(org):
            async with open_session() as db:
                for t in tables:
                    seen = (await db.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one()  # noqa: S608
                    if seen != truth[(t, org)]:
                        wrong.append(f"{t}: tenant sees {seen} rows, owns {truth[(t, org)]}")
                    try:
                        async with db.begin_nested():
                            changed = (await db.execute(
                                text(f"UPDATE {t} SET org_id = org_id WHERE org_id = :o"),  # noqa: S608
                                {"o": other})).rowcount
                    except ProgrammingError as exc:   # audit_logs: no UPDATE for the app at all
                        assert "permission denied" in str(exc)
                        changed = 0
                    if changed:
                        wrong.append(f"{t}: tenant updated {changed} of another organisation's rows")
                await db.rollback()
                # a row written for another organisation is refused (the policy's WITH CHECK)
                with pytest.raises(Exception, match="row-level security"):
                    await db.execute(text("INSERT INTO organizations (name) VALUES ('Sneaky')"))
                await db.rollback()
                with pytest.raises(Exception, match="row-level security"):
                    await db.execute(text(
                        "INSERT INTO company_leaves (org_id, manager_id, employee_code, leave_date) "
                        "SELECT :o, id, 'X', DATE '2026-01-01' FROM users LIMIT 1"), {"o": other})
                await db.rollback()
    with tenant(None):   # no tenant at all: nothing is visible
        async with open_session() as db:
            for t in [*tables, "organizations"]:
                if n := (await db.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one():  # noqa: S608
                    wrong.append(f"{t}: {n} rows visible with no tenant set")
    assert not wrong, "\n".join(wrong)


async def test_a_row_cannot_be_created_without_an_organisation():
    with tenant(None):
        async with open_session() as db:
            # refused by the policy (checked first) or, failing that, by NOT NULL
            with pytest.raises(Exception, match='row-level security|null value in column "org_id"'):
                await db.execute(text(
                    "INSERT INTO approved_m365_domains (domain, is_active) VALUES ('x.example', true)"))
