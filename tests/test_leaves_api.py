"""company leave register API: CRUD, idempotency, scoping, validation."""

from tests.helpers import admin, create_user, csv_file, manager


class TestLeavesApi:
    async def test_manager_adds_lists_and_deletes(self, client, ma_user_id):
        h = await manager(client, "lv.crud")
        r = await client.post("/api/v1/leaves", json={"employee_code": "100001", "start_date": "2026-07-20",
                                                      "end_date": "2026-07-22", "leave_type": "Sick"}, headers=h)
        assert r.status_code == 201 and r.json()["inserted"] == 3
        listing = (await client.get("/api/v1/leaves?month=2026-07", headers=h)).json()
        assert listing["total"] == 3
        assert {i["leave_date"] for i in listing["items"]} == {"2026-07-20", "2026-07-21", "2026-07-22"}
        leave_id = listing["items"][0]["id"]
        assert (await client.delete(f"/api/v1/leaves/{leave_id}", headers=h)).status_code == 204
        assert (await client.get("/api/v1/leaves", headers=h)).json()["total"] == 2
        assert (await client.delete(f"/api/v1/leaves/{leave_id}", headers=h)).status_code == 404

    async def test_re_adding_the_same_days_is_idempotent(self, client, ma_user_id):
        h = await manager(client, "lv.idem")
        body = {"employee_code": "100001", "start_date": "17-07-2026"}
        assert (await client.post("/api/v1/leaves", json=body, headers=h)).json()["inserted"] == 1
        assert (await client.post("/api/v1/leaves", json=body, headers=h)).json()["inserted"] == 0

    async def test_register_upload_expands_ranges_and_dedupes(self, client, ma_user_id):
        h = await manager(client, "lv.upload")
        csv = ("Employee ID,From Date,To Date,Leave Type\n"
               "100001,21-07-2026,23-07-2026,Earned\n"
               "100001,22-07-2026,,Earned\n"          # overlaps the range
               "bad id!,21-07-2026,,x\n"                # rejected, not fatal
               "100004,not a date,,x\n")
        r = await client.post("/api/v1/uploads?kind=COMPANY_LEAVE", files=[csv_file("l.csv", csv)], headers=h)
        assert r.status_code == 201 and r.json()["status"] == "COMPLETED"
        assert (await client.get("/api/v1/leaves", headers=h)).json()["total"] == 3

    async def test_validation_errors(self, client, ma_user_id):
        h = await manager(client, "lv.bad")
        bad = [
            {"employee_code": "100001", "start_date": "32-13-2026"},
            {"employee_code": "100001", "start_date": "2026-07-10", "end_date": "2026-07-01"},
            {"employee_code": "100001", "start_date": "2026-01-01", "end_date": "2026-12-31"},
            {"employee_code": "no spaces allowed", "start_date": "2026-07-01"},
        ]
        for body in bad:
            r = await client.post("/api/v1/leaves", json=body, headers=h)
            assert r.status_code == 422, (body, r.text)
        assert (await client.get("/api/v1/leaves?month=2026-13", headers=h)).status_code == 422

    async def test_scoping_between_managers_hr_and_admin(self, client, ma_user_id):
        ma = await admin(client)
        _, m1 = await create_user(client, ma, "lv.m1@veritrack.io", "MANAGER")
        _, m2 = await create_user(client, ma, "lv.m2@veritrack.io", "MANAGER")
        _, hr1 = await create_user(client, m1, "lv.hr1@veritrack.io", "HR")
        await client.post("/api/v1/leaves", json={"employee_code": "111111", "start_date": "2026-07-01"}, headers=m1)
        await client.post("/api/v1/leaves", json={"employee_code": "222222", "start_date": "2026-07-01"}, headers=m2)

        async def codes(h):
            return {i["employee_code"] for i in (await client.get("/api/v1/leaves", headers=h)).json()["items"]}

        assert await codes(m1) == {"111111"}
        assert await codes(hr1) == {"111111"}
        assert (await client.get("/api/v1/leaves", headers=ma)).json()["total"] == 2
        # HR and admins are read-only; managers can't delete each other's rows
        body = {"employee_code": "111111", "start_date": "2026-07-02"}
        r = await client.post("/api/v1/leaves", json=body, headers=hr1)
        assert r.status_code == 403
        other = (await client.get("/api/v1/leaves", headers=m2)).json()["items"][0]["id"]
        assert (await client.delete(f"/api/v1/leaves/{other}", headers=m1)).status_code == 404
