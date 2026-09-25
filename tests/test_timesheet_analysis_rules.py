"""Timesheet leave rule — unit level and edge cases through the API."""

from datetime import date

from app.services import gets_rules
from app.services.extraction.normalize import normalize_tables
from app.services.extraction.readers import RawTable
from tests.helpers import csv_file, manager


def _ts(code="100001", ooo=True, days=(17, 27), period="2026-07", review=False):
    return {
        "employee_code": code,
        "full_name": "X",
        "extra": {"hour_type": "NC", "project_name": "Out Of Office" if ooo else "Safety",
                  "is_out_of_office": ooo, "leave_days": list(days), "period": period},
    }


def test_customer_leave_dates_from_ooo_rows_only():
    assert gets_rules.customer_leave_dates(_ts()) == [date(2026, 7, 17), date(2026, 7, 27)]
    assert gets_rules.customer_leave_dates(_ts(ooo=False)) == []
    assert gets_rules.customer_leave_dates(_ts(period="")) == []
    assert gets_rules.customer_leave_dates(_ts(days=(31,), period="2026-06")) == []  # 31 June does not exist


def test_evaluate_timesheet_leave():
    cust = {date(2026, 7, 17), date(2026, 7, 27)}
    assert gets_rules.evaluate_timesheet_leave(cust, cust) == (False, "", [])
    violation, reason, missing = gets_rules.evaluate_timesheet_leave(cust, {date(2026, 7, 17)})
    assert violation and missing == [date(2026, 7, 27)] and "27 Jul 2026" in reason
    assert gets_rules.evaluate_timesheet_leave(set(), set())[0] is False


def test_timesheet_rows_are_recognised():
    assert gets_rules.is_timesheet_row(_ts())
    assert not gets_rules.is_timesheet_row({"employee_code": "E-1", "customer_leave": "x"})


def test_gets_spreadsheet_export_normalises_by_header_names():
    headers = ["Person ID", "Supplier", "Billable Job Family", "UOM", "Project ID", "Sub Project",
               "Sub Project ID", "Remarks", *[str(d) for d in range(1, 32)], "Total"]
    row = ["100001", "ACME", "Engineer", "NC", "600001", "Out Of Office", "2100001", "",
           *["8" if d in (17, 27) else "" for d in range(1, 32)], "16"]
    [n] = normalize_tables([RawTable(headers=headers, rows=[row])])
    extra = n.values["extra"]
    assert n.employee_code == "100001"
    assert extra["hour_type"] == "NC" and extra["day_17"] == 8 and extra["total"] == 16
    assert extra["is_out_of_office"] and extra["leave_days"] == [17, 27]


REPO = "Employee ID,Full Name,Company Email\n100001,Alpha,alpha@example.com\n"


class TestTimesheetAnalysisEdges:
    async def test_timesheet_export_without_period_never_raises_false_violations(self, client, ma_user_id):
        """A GETS spreadsheet export carries no month: its Out Of Office days
        cannot be dated, so they must not be reported as missing leave."""
        h = await manager(client, "ts.edge")
        await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO", files=[csv_file("r.csv", REPO)], headers=h)
        headers = ["Person ID", "UOM", "Sub Project", *[str(d) for d in range(1, 32)], "Total"]
        row = ["100001", "NC", "Out Of Office", *["8" if d == 17 else "" for d in range(1, 32)], "8"]
        text = ",".join(headers) + "\n" + ",".join(row) + "\n"
        batch = (await client.post("/api/v1/uploads?kind=GETS", files=[csv_file("g.csv", text)], headers=h)).json()
        r = await client.post(f"/api/v1/batches/{batch['id']}/analyze", headers=h)
        assert r.status_code == 202 and r.json()["violations"] == 0 and r.json()["matched"] == 1

    async def test_analyze_twice_conflicts(self, client, ma_user_id):
        h = await manager(client, "ts.twice")
        batch = (await client.post("/api/v1/uploads?kind=GETS",
                                   files=[csv_file("g.csv", "Employee ID,Name,Customer Leave,Company Leave\n"
                                                           "E-1,A,x,\n")],
                                   headers=h)).json()
        assert (await client.post(f"/api/v1/batches/{batch['id']}/analyze", headers=h)).status_code == 202
        second = await client.post(f"/api/v1/batches/{batch['id']}/analyze", headers=h)
        assert second.status_code == 409 and second.json()["error"]["code"] == "already_analyzed"

    async def test_employee_repo_batch_cannot_be_analyzed(self, client, ma_user_id):
        h = await manager(client, "ts.kind")
        batch = (await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO",
                                   files=[csv_file("r.csv", REPO)], headers=h)).json()
        r = await client.post(f"/api/v1/batches/{batch['id']}/analyze", headers=h)
        assert r.status_code == 400 and r.json()["error"]["code"] == "wrong_kind"

    async def test_employees_csv_export(self, client, ma_user_id):
        h = await manager(client, "ts.export")
        await client.post("/api/v1/uploads?kind=EMPLOYEE_REPO", files=[csv_file("r.csv", REPO)], headers=h)
        r = await client.get("/api/v1/employees/export.csv", headers=h)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        lines = r.text.strip().splitlines()
        assert lines[0].startswith("employee_code,full_name") and "100001" in lines[1]


def _sheet(verified: bool, issues: list[str]) -> dict:
    return {
        "verified": verified, "period": "2026-07", "person_id": "100001", "employee_name": "SAMPLE, A (A.)",
        "checks": [] if verified else [{"check": "STD grand total", "ok": False}],
        "lines": [{
            "person_id": "100001", "uom": "STD", "sub_project": "Alpha", "printed_total": 8,
            "confidence": 0.8, "issues": issues,
            "cells": [{"day": 1, "hours": 8, "status": "USER_SIGNED"}],
        }],
    }


def test_verified_sheet_does_not_flag_low_confidence_digits():
    from app.services.extraction.normalize import normalize_gets_sheet

    [row] = normalize_gets_sheet(_sheet(True, ["day 1: low-confidence read '8' (0.80)"]))
    assert not row.needs_review


def test_unverified_sheet_is_flagged_for_review():
    from app.services.extraction.normalize import normalize_gets_sheet

    [row] = normalize_gets_sheet(_sheet(False, ["day 1: low-confidence read '8' (0.80)"]))
    assert row.needs_review and "totals cross-check failed" in row.review_note
