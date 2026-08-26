"""Employee repository: versioning, inline corrections, history, scoping."""

import io

from tests.conftest import (
    MA_EMAIL,
    MA_PASSWORD,
)

REPO_V1 = b"""Employee ID,Full Name,Company Email,Personal Email,Dept
E-100,Ann Weaver,ann@corp.io,ann@gmail.com,Ops
E-200,Bob Chen,bob@corp.io,,
"""

REPO_V2 = b"""Employee ID,Full Name,Company Email,Personal Email,Dept
E-100,Ann Weaver-Smith,ann@corp.io,ann@gmail.com,Ops
E-200,Bob Chen,bob@corp.io,,
E-300,Cid Reyes,,,
"""


async def _make_manager(client):
    login = await client.post(
        "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD}
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = await client.post(
        "/api/v1/users",
        json={"email": "repo.manager@veritrack.io", "role": "MANAGER"},
        headers=h,
    )
    pw = created.json()["initial_password"]
    m = await client.post(
        "/api/v1/auth/login",
        json={"email": "repo.manager@veritrack.io", "password": pw},
    )
    return {"Authorization": f"Bearer {m.json()['access_token']}"}


def _csv(name: str, text: str):
    return ("files", (name, io.BytesIO(text.encode()), "text/csv"))


class TestVersioning:
    async def test_reupload_creates_versions_not_overwrites(self, client, ma_user_id):
        headers = await _make_manager(client)

        r1 = await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO",
                               files=[_csv("v1.csv", REPO_V1.decode())], headers=headers)
        assert r1.status_code == 201

        listing = (await client.get("/api/v1/employees", headers=headers)).json()
        assert listing["total"] == 2
        ann = next(e for e in listing["items"] if e["employee_code"] == "E-100")

        history1 = (await client.get(
            f"/api/v1/employees/{ann['id']}/history", headers=headers)).json()
        assert len(history1["items"]) == 1
        assert history1["items"][0]["change_source"] == "UPLOAD"

        # Re-upload with a changed surname for E-100 + brand new E-300.
        r2 = await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO",
                               files=[_csv("v2.csv", REPO_V2.decode())], headers=headers)
        assert r2.status_code == 201

        listing2 = (await client.get("/api/v1/employees", headers=headers)).json()
        assert listing2["total"] == 3  # non-destructive: E-300 added, others kept
        ann2 = next(e for e in listing2["items"] if e["employee_code"] == "E-100")
        assert ann2["full_name"] == "Ann Weaver-Smith"  # current view updated

        history2 = (await client.get(
            f"/api/v1/employees/{ann['id']}/history", headers=headers)).json()
        versions = history2["items"]
        assert len(versions) == 2
        assert versions[0]["version"] > versions[1]["version"]  # desc order
        old = versions[-1]
        assert old["full_name"] == "Ann Weaver"  # original preserved verbatim

    async def test_inline_correction(self, client, ma_user_id):
        headers = await _make_manager(client)
        await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO",
                          files=[_csv("v1.csv", REPO_V1.decode())], headers=headers)
        listing = (await client.get("/api/v1/employees", headers=headers)).json()
        bob = next(e for e in listing["items"] if e["employee_code"] == "E-200")

        r = await client.patch(
            f"/api/v1/employees/{bob['id']}",
            json={"department": "Marketing", "personal_email": "bobby@x.com",
                  "note": "moved teams"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["version"] == 2
        assert r.json()["department"] == "Marketing"

        current = (await client.get("/api/v1/employees", headers=headers)).json()
        bob_now = next(e for e in current["items"] if e["employee_code"] == "E-200")
        assert bob_now["department"] == "Marketing"
        assert bob_now["official_email"] == "bob@corp.io"  # untouched fields kept

        history = (await client.get(
            f"/api/v1/employees/{bob['id']}/history", headers=headers)).json()
        sources = [v["change_source"] for v in history["items"]]
        assert sources == ["CORRECTION", "UPLOAD"]

    async def test_invalid_email_correction_rejected(self, client, ma_user_id):
        headers = await _make_manager(client)
        await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO",
                          files=[_csv("v1.csv", REPO_V1.decode())], headers=headers)
        listing = (await client.get("/api/v1/employees", headers=headers)).json()
        ann = next(e for e in listing["items"] if e["employee_code"] == "E-100")
        r = await client.patch(
            f"/api/v1/employees/{ann['id']}",
            json={"official_email": "not-an-email"},
            headers=headers,
        )
        assert r.status_code == 422

    async def test_manager_sees_only_own_repo(self, client, ma_user_id):

        # Manager A uploads
        headers_a = await _make_manager(client)
        await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO",
                          files=[_csv("v1.csv", REPO_V1.decode())],
                          headers=headers_a)

        # Manager B has an empty repository
        login = await client.post(
            "/api/v1/auth/login", json={"email": MA_EMAIL, "password": MA_PASSWORD})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}
        created = await client.post(
            "/api/v1/users",
            json={"email": "other.manager@veritrack.io", "role": "MANAGER"},
            headers=h)
        pw = created.json()["initial_password"]
        mlogin = await client.post(
            "/api/v1/auth/login",
            json={"email": "other.manager@veritrack.io", "password": pw})
        headers_b = {"Authorization": f"Bearer {mlogin.json()['access_token']}"}

        empty = (await client.get("/api/v1/employees", headers=headers_b)).json()
        assert empty["total"] == 0

        full = (await client.get("/api/v1/employees", headers=headers_a)).json()
        assert full["total"] == 2

        # MA sees all managers' employees
        all_seen = (await client.get("/api/v1/employees", headers=h)).json()
        assert all_seen["total"] == 2
