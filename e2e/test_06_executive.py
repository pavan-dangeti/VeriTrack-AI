"""Executive: org-wide read-only oversight + drill-down."""

import re

from catalog import FORBIDDEN, visit_every_sidebar_page
from conftest import grid_filter
from playwright.sync_api import expect


def test_executive_every_page(executive, manager_ready):
    p = executive.page
    expect(p.locator("main h1")).to_have_text("Dashboard")
    expect(p.get_by_test_id("profile-link")).to_contain_text("Executive")
    executive.shot("exec-00-first-login")
    visit_every_sidebar_page(executive, "EXECUTIVE", "exec")
    executive.nav("Dashboard", "/dashboard", "Dashboard")
    for m in ("Employees", "Batches uploaded", "Analysis runs", "Violations detected", "Emails sent"):
        expect(p.get_by_test_id(f"metric-{m}").locator("p.text-3xl")).to_have_text(re.compile(r"^\d+$"))
    for title, path in (("Analytics", "/analytics"), ("All reports", "/all-reports"), ("Directory", "/directory")):
        p.locator("main").get_by_role("link").filter(has_text=title).click()
        p.wait_for_url(re.compile(re.escape(path) + "$"))
        executive.settle()
        p.go_back()
        executive.settle()


def test_executive_analytics_and_repositories(executive, manager_ready, manager_account):
    p = executive.page
    executive.nav("Analytics", "/analytics", "Analytics")
    expect(p.get_by_test_id("analytics-page")).to_contain_text("System-wide, all managers.")
    expect(p.get_by_test_id("by-manager-table")).to_be_visible()
    executive.nav("All Employee Repositories", "/all-employees", "All Employee Repositories")
    grid = p.get_by_test_id("employees-grid")
    grid_filter(p, "employee_code", "197061")
    expect(grid.locator(".ag-row:has([col-id=employee_code])").first).to_contain_text("Echo Specimen")
    expect(p.get_by_test_id("upload-repo")).to_have_count(0)
    executive.nav("Company Leave Register", "/leaves", "Company Leave Register")
    expect(p.get_by_test_id("add-leave")).to_have_count(0)
    expect(p.get_by_test_id("leave-file-input")).to_have_count(0)


def test_executive_all_reports_and_results(executive, manager_ready):
    p = executive.page
    bid = manager_ready["gets_batch_id"]
    executive.nav("All Reports", "/all-reports", "All Reports")
    card = p.locator("main div.rounded-2xl").filter(has=p.locator(f"a[href='/analysis/{bid}']"))
    expect(card).to_have_count(1)
    executive.expect_download(
        lambda: card.get_by_role("button", name="Summary PDF").click(), min_bytes=500, suffix=".pdf"
    )
    executive.expect_download(
        lambda: card.get_by_role("button", name="3-tab Excel").click(), min_bytes=1000, suffix=".xlsx"
    )
    card.get_by_role("button", name="View results").click()
    p.wait_for_url(re.compile(rf"/analysis/{bid}$"))
    executive.settle()
    rows = p.get_by_test_id("violations-table").locator("tbody tr")
    expect(rows).to_have_count(2)
    expect(rows.filter(has_text="141220")).to_contain_text("Jul 28")
    expect(rows.filter(has_text="197061")).to_contain_text("Jun 18")
    executive.shot("exec-analysis-results")
    p.get_by_role("button", name="Back").click()
    p.wait_for_url(re.compile(r"/all-reports$"))


def test_executive_directory_drill_down(executive, manager_ready, manager_account, hr_account):
    p = executive.page
    executive.nav("Manager & HR Directory", "/directory", "Manager & HR Directory")
    table = p.locator("main table")
    mrow = table.locator("tr").filter(has_text=manager_account["email"])
    expect(mrow).to_contain_text("MANAGER")
    expect(table.locator("tr").filter(has_text=hr_account["email"])).to_contain_text("HR")
    expect(table.locator("tbody tr").filter(has_text="MASTER_ADMIN")).to_have_count(0)
    executive.shot("exec-directory")

    mrow.get_by_role("link").click()
    p.wait_for_url(re.compile(r"/people/[0-9a-f-]{36}$"))
    executive.settle()
    prof = p.get_by_test_id("user-profile-page")
    expect(prof).to_contain_text("Manager profile")
    expect(p.get_by_test_id("profile-batches-table").locator("tbody tr").first).to_contain_text("Completed")
    executive.shot("exec-people-manager")
    manager_url = p.url

    p.get_by_test_id("profile-hr-table").get_by_role("link").filter(has_text=re.compile(".+")).first.click()
    p.wait_for_url(re.compile(r"/people/[0-9a-f-]{36}$"))
    executive.settle()
    expect(p.get_by_test_id("user-profile-page")).to_contain_text("HR profile")
    executive.shot("exec-people-hr")
    p.get_by_test_id("user-profile-page").get_by_role("link").click()
    p.wait_for_url(manager_url)
    executive.settle()
    p.get_by_test_id("back-button").click()
    executive.settle()
    expect(p.get_by_test_id("user-profile-page")).to_contain_text("HR profile")


def test_executive_blocked_urls(executive):
    for path in FORBIDDEN["EXECUTIVE"]:
        executive.expect_denied(path)
    executive.shot("exec-access-denied")
    executive.page.get_by_role("button", name="Back to dashboard").click()
    executive.page.wait_for_url(re.compile(r"/dashboard$"))
    executive.settle()
