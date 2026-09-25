"""Master Admin cross-manager views, now that a manager has real data."""

import re

from conftest import ACCOUNTS, grid_filter
from playwright.sync_api import expect


def test_admin_all_gets_uploads(admin, manager_ready, manager_account):
    p = admin.page
    bid = manager_ready["gets_batch_id"]
    admin.goto("/dashboard")
    admin.nav("All GETS Uploads", "/all-uploads", "All GETS Uploads")
    card = p.get_by_test_id(f"batch-{bid}")
    expect(card).to_be_visible()
    expect(p.get_by_test_id(f"uploader-{bid}")).to_contain_text(manager_account["email"])
    expect(p.get_by_test_id("gets-file-input")).to_have_count(0)
    expect(card.get_by_role("button", name="Run analysis")).to_have_count(0)
    card.get_by_test_id("inspect").click()
    files = card.get_by_test_id("progress-card").locator("tbody tr")
    expect(files).to_have_count(4)
    expect(card.get_by_role("button", name="Re-extract")).to_have_count(0)
    admin.shot("admin-all-uploads-expanded")
    f = admin.expect_download(lambda: card.get_by_role("button", name="Export").click(), min_bytes=1000, suffix=".xlsx")
    assert f.read_bytes()[:2] == b"PK"

    files.first.get_by_role("button", name="Review").click()
    p.wait_for_url(re.compile(rf"/review/{bid}/"))
    admin.settle()
    expect(p.get_by_test_id("timesheet-grid")).to_be_visible()
    admin.shot("admin-sheet-review")
    p.get_by_test_id("back-button").click()
    p.wait_for_url(re.compile(r"/all-uploads$"))
    admin.settle()

    p.get_by_test_id(f"batch-{bid}").get_by_role("button", name="Results").click()
    p.wait_for_url(re.compile(rf"/analysis/{bid}$"))
    admin.settle()
    expect(p.get_by_test_id("violations-table").locator("tbody tr")).to_have_count(2)
    admin.shot("admin-analysis-results")
    admin.expect_download(lambda: p.get_by_role("button", name="Summary PDF").click(), min_bytes=500, suffix=".pdf")
    admin.expect_download(lambda: p.get_by_role("button", name="Excel report").click(), min_bytes=1000, suffix=".xlsx")


def test_admin_all_employees_readonly(admin, manager_ready):
    p = admin.page
    admin.nav("All Employee Repositories", "/all-employees", "All Employee Repositories")
    grid = p.get_by_test_id("employees-grid")
    expect(grid.locator(".ag-row:has([col-id=employee_code])").first).to_be_visible()
    grid_filter(p, "employee_code", "141220")
    rows = grid.locator(".ag-row:has([col-id=employee_code])")
    expect(rows.first).to_contain_text("141220")
    for i in range(rows.count()):
        expect(rows.nth(i).locator("[col-id=employee_code]")).to_have_text("141220")
    expect(p.get_by_test_id("upload-repo")).to_have_count(0)
    expect(grid.get_by_role("link")).to_have_count(0)
    grid.locator(".ag-row [col-id=full_name]").first.dblclick()
    expect(grid.locator(".ag-cell-inline-editing")).to_have_count(0)
    admin.shot("admin-all-employees")


def test_admin_all_reports(admin, manager_ready):
    p = admin.page
    bid = manager_ready["gets_batch_id"]
    admin.nav("All Reports", "/all-reports", "All Reports")
    card = p.locator("main div.rounded-2xl").filter(has=p.locator(f"a[href='/analysis/{bid}']"))
    expect(card).to_have_count(1)
    expect(card).to_contain_text("2 violations")
    admin.shot("admin-all-reports")
    admin.expect_download(lambda: card.get_by_role("button", name="Summary PDF").click(), min_bytes=500, suffix=".pdf")
    admin.expect_download(
        lambda: card.get_by_role("button", name="3-tab Excel").click(), min_bytes=1000, suffix=".xlsx"
    )
    card.get_by_role("button", name="View results").click()
    p.wait_for_url(re.compile(rf"/analysis/{bid}$"))
    admin.settle()
    expect(p.get_by_test_id("analysis-page")).to_be_visible()


def test_admin_leaves_readonly_and_analytics(admin, manager_ready, manager_account):
    p = admin.page
    admin.nav("Company Leave Register", "/leaves", "Company Leave Register")
    expect(p.get_by_test_id("add-leave")).to_have_count(0)
    expect(p.get_by_test_id("leave-file-input")).to_have_count(0)
    p.get_by_test_id("leave-month").fill("2025-06")
    admin.settle()
    expect(p.get_by_role("button", name=re.compile(r"^Delete leave"))).to_have_count(0)
    admin.shot("admin-leaves-readonly")

    admin.nav("Analytics", "/analytics", "Analytics")
    ap = p.get_by_test_id("analytics-page")
    expect(ap).to_contain_text("System-wide, all managers.")
    who = ACCOUNTS["MANAGER"].get("name") or manager_account["email"]
    expect(p.get_by_test_id("by-manager-table")).to_contain_text(who)
    admin.shot("admin-analytics-populated")

    admin.nav("Dashboard", "/dashboard", "Dashboard")
    p.reload()
    admin.settle()
    expect(p.get_by_test_id("metric-Violations detected").locator("p.text-3xl")).to_have_text(re.compile(r"^[1-9]\d*$"))
