"""Profile pages + drill-down: content per role and RBAC scoping.

Covers: GET /users/{id}/profile (self + drill-down) and
GET /employees/{id}/detail — including the locked requirement that a
MANAGER can never read another MANAGER's HR or employee records by ID.
"""

import io

from tests.conftest import MA_EMAIL, MA_PASSWORD

REPO_CSV = b"Employee ID,Full Name,Company Email,Personal Email,Dept\nE-100,Ann Weaver,ann@corp.io,ann@gmail.com,Ops\n"
GETS_CSV = b"Employee ID,Full Name,Total\nE-100,Ann Weaver,8\n"


async def _login(client, email, password):
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _create_user(client, headers, email, role):
    r = await client.post("/api/v1/users", json={"email": email, "role": role}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _make_manager(client, ma_headers, label):
    created = await _create_user(client, ma_headers, f"{label}.manager@veritrack.io", "MANAGER")
    headers = await _login(client, f"{label}.manager@veritrack.io", created["initial_password"])
    return created["user"]["id"], headers


async def _make_hr(client, manager_headers, label):
    created = await _create_user(client, manager_headers, f"{label}.hr@veritrack.io", "HR")
    headers = await _login(client, f"{label}.hr@veritrack.io", created["initial_password"])
    return created["user"]["id"], headers


def _csv(name, content):
    return ("files", (name, io.BytesIO(content), "text/csv"))


class TestFullName:
    async def test_create_with_full_name_roundtrip(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        created = await client.post(
            "/api/v1/users",
            json={"email": "named.mgr@veritrack.io", "role": "MANAGER",
                  "full_name": "Priya Nair"},
            headers=ma,
        )
        assert created.status_code == 201, created.text
        uid = created.json()["user"]["id"]
        assert created.json()["user"]["full_name"] == "Priya Nair"

        listing = (await client.get("/api/v1/users", headers=ma)).json()
        assert any(u["full_name"] == "Priya Nair" for u in listing["items"])

        profile = (await client.get(f"/api/v1/users/{uid}/profile", headers=ma)).json()
        assert profile["full_name"] == "Priya Nair"

    async def test_full_name_optional_legacy_accounts_fall_back(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        created = await _create_user(client, ma, "unnamed.mgr@veritrack.io", "MANAGER")
        assert created["user"]["full_name"] is None  # nullable column, no break

        # HR accounts nested in a profile carry full_name key too (None here)
        mgr_id = created["user"]["id"]
        mgr = await _login(client, "unnamed.mgr@veritrack.io", created["initial_password"])
        await _make_hr(client, mgr, "legacy")
        profile = (await client.get(f"/api/v1/users/{mgr_id}/profile", headers=ma)).json()
        assert profile["hr_accounts"][0]["full_name"] is None
        assert profile["full_name"] is None


class TestUserProfileContent:
    async def test_manager_profile_counts_and_hr_list(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        mgr_id, mgr = await _make_manager(client, ma, "p1")
        hr_id, _ = await _make_hr(client, mgr, "p1")
        await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO", files=[_csv("r.csv", REPO_CSV)], headers=mgr)
        await client.post("/api/v1/uploads?kind=GETS", files=[_csv("g.csv", GETS_CSV)], headers=mgr)

        r = await client.get(f"/api/v1/users/{mgr_id}/profile", headers=ma)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["email"] == "p1.manager@veritrack.io"
        assert body["created_at"] and body["role"] == "MANAGER"
        assert [h["id"] for h in body["hr_accounts"]] == [hr_id]
        assert body["employee_count"] == 1
        assert body["gets_batches_total"] == 1
        assert len(body["gets_batches_recent"]) == 1

        # last_login_at is set for an account that has logged in
        assert body["last_login_at"] is not None

    async def test_executive_can_view_manager_and_hr_profiles(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        execu = await _create_user(client, ma, "prof.exec@veritrack.io", "EXECUTIVE")
        ex = await _login(client, "prof.exec@veritrack.io", execu["initial_password"])
        mgr_id, mgr = await _make_manager(client, ma, "p2")
        hr_id, _ = await _make_hr(client, mgr, "p2")

        r = await client.get(f"/api/v1/users/{hr_id}/profile", headers=ex)
        assert r.status_code == 200, r.text
        assert r.json()["manager"]["id"] == mgr_id

    async def test_self_profile_all_roles(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        me = (await client.get("/api/v1/auth/me", headers=ma)).json()
        r = await client.get(f"/api/v1/users/{me['id']}/profile", headers=ma)
        assert r.status_code == 200 and r.json()["role"] == "MASTER_ADMIN"

        mgr_id, mgr = await _make_manager(client, ma, "p3")
        hr_id, hr = await _make_hr(client, mgr, "p3")
        r = await client.get(f"/api/v1/users/{hr_id}/profile", headers=hr)
        assert r.status_code == 200
        assert r.json()["manager"]["id"] == mgr_id


class TestProfileRbacScoping:
    async def test_manager_cannot_view_other_managers_hr(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        _, mgr_a = await _make_manager(client, ma, "a")
        _, mgr_b = await _make_manager(client, ma, "b")
        hr_b_id, _ = await _make_hr(client, mgr_b, "b")

        r = await client.get(f"/api/v1/users/{hr_b_id}/profile", headers=mgr_a)
        assert r.status_code == 403

    async def test_manager_cannot_view_other_manager(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        _, mgr_a = await _make_manager(client, ma, "c")
        mgr_b_id, _ = await _make_manager(client, ma, "d")
        r = await client.get(f"/api/v1/users/{mgr_b_id}/profile", headers=mgr_a)
        assert r.status_code == 403

    async def test_hr_cannot_view_others_profiles(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        mgr_id, mgr = await _make_manager(client, ma, "e")
        hr_id, hr = await _make_hr(client, mgr, "e")
        r = await client.get(f"/api/v1/users/{mgr_id}/profile", headers=hr)
        assert r.status_code == 403
        other_mgr_id, _ = await _make_manager(client, ma, "f")
        r = await client.get(f"/api/v1/users/{other_mgr_id}/profile", headers=hr)
        assert r.status_code == 403

    async def test_unauthenticated_profile_request_rejected(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        me = (await client.get("/api/v1/auth/me", headers=ma)).json()
        r = await client.get(f"/api/v1/users/{me['id']}/profile")
        assert r.status_code == 401


class TestEmployeeDetail:
    async def _seed_employee(self, client, mgr):
        await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO", files=[_csv("r.csv", REPO_CSV)], headers=mgr)
        listing = (await client.get("/api/v1/employees", headers=mgr)).json()
        return listing["items"][0]

    async def test_detail_has_record_versions_and_batches(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        _, mgr = await _make_manager(client, ma, "g")
        emp = await self._seed_employee(client, mgr)
        await client.post("/api/v1/uploads?kind=GETS", files=[_csv("g.csv", GETS_CSV)], headers=mgr)

        r = await client.get(f"/api/v1/employees/{emp['id']}/detail", headers=mgr)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["employee_code"] == "E-100"
        assert body["full_name"] == "Ann Weaver"
        assert body["official_email"] == "ann@corp.io"
        assert len(body["versions"]) == 1 and body["versions"][0]["change_source"] == "UPLOAD"
        assert len(body["gets_batches"]) == 1

    async def test_manager_cannot_view_other_managers_employee(self, client, ma_user_id):
        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        _, mgr_a = await _make_manager(client, ma, "h")
        _, mgr_b = await _make_manager(client, ma, "i")
        emp = await self._seed_employee(client, mgr_a)
        r = await client.get(f"/api/v1/employees/{emp['id']}/detail", headers=mgr_b)
        assert r.status_code == 403

    async def test_missing_employee_404(self, client, ma_user_id):
        import uuid

        ma = await _login(client, MA_EMAIL, MA_PASSWORD)
        r = await client.get(f"/api/v1/employees/{uuid.uuid4()}/detail", headers=ma)
        assert r.status_code == 404
