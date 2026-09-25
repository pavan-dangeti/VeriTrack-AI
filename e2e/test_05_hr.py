"""HR (created by the manager through the UI): read-only access."""

import re

from catalog import FORBIDDEN, visit_every_sidebar_page
from playwright.sync_api import expect


def test_hr_first_login_and_every_page(hr, manager_ready):
    p = hr.page
    expect(p).to_have_url(re.compile(r"/dashboard$"))  # no forced password change
    expect(p.locator("main h1")).to_have_text("Team Overview")
    expect(p.get_by_test_id("profile-link")).to_contain_text("HR")
    hr.shot("hr-00-first-login")
    visit_every_sidebar_page(hr, "HR", "hr")

    hr.nav("Dashboard", "/dashboard", "Team Overview")
    for m in ("Employees", "Batches uploaded"):
        expect(p.get_by_test_id(f"metric-{m}").locator("p.text-3xl")).to_have_text(re.compile(r"^\d+$"))
    expect(p.get_by_test_id("metric-Analysis runs")).to_have_count(0)
    expect(p.get_by_test_id("hr-latest-batch")).to_contain_text("COMPLETED")
    for title, path in (
        ("Monthly GETS sheets", "/gets-sheets"),
        ("Leave register", "/leaves"),
        ("Employee data", "/employee-data"),
    ):
        p.locator("main").get_by_role("link").filter(has_text=title).click()
        p.wait_for_url(re.compile(re.escape(path) + "$"))
        hr.settle()
        p.go_back()
        hr.settle()


def test_hr_dashboard_counts_are_scoped_to_their_manager(hr, manager_ready):
    """HR's dashboard says "Scope: your workspace" — the numbers must be the
    manager's (4 employees), not the whole organisation's."""
    p = hr.page
    hr.goto("/dashboard")
    p.reload()
    hr.settle()
    expect(p.get_by_text("Scope: your workspace")).to_be_visible()
    hr.shot("hr-dashboard-counts")
    expect(p.get_by_test_id("metric-Employees").locator("p.text-3xl")).to_have_text("4")


def test_hr_employee_data_download(hr, manager_ready):
    p = hr.page
    hr.nav("Employee Data", "/employee-data", "Employee Data")
    rows = p.get_by_test_id("hr-employees").locator("tbody tr")
    expect(rows).to_have_count(4)
    expect(rows.filter(has_text="141220")).to_contain_text("Bravo Example")
    f = hr.expect_download(lambda: p.get_by_role("button", name="Download CSV").click(), suffix=".csv")
    text = f.read_text()
    for code in ("103729", "158082", "141220", "197061"):
        assert code in text, text[:300]


def test_hr_gets_sheets_download_only(hr, manager_ready):
    p = hr.page
    hr.nav("Monthly GETS Sheets", "/gets-sheets", "Monthly GETS Sheets")
    cards = p.locator("main div.rounded-2xl").filter(has=p.get_by_role("button", name="Download export"))
    expect(cards.first).to_be_visible()
    expect(cards.first.locator("[data-status=COMPLETED]")).to_be_visible()
    expect(p.get_by_test_id("gets-file-input")).to_have_count(0)
    expect(p.get_by_role("button", name=re.compile("Run analysis|Re-extract|Review"))).to_have_count(0)
    f = hr.expect_download(
        lambda: cards.first.get_by_role("button", name="Download export").click(), min_bytes=1000, suffix=".xlsx"
    )
    assert f.read_bytes()[:2] == b"PK"
    hr.shot("hr-gets-sheets")


def test_hr_leave_register_read_only(hr, manager_ready):
    p = hr.page
    hr.nav("Company Leave Register", "/leaves", "Company Leave Register")
    expect(p.get_by_test_id("add-leave")).to_have_count(0)
    expect(p.get_by_test_id("leave-file-input")).to_have_count(0)
    p.get_by_test_id("leave-month").fill("2025-06")
    rows = p.get_by_test_id("leaves-table").locator("tbody tr")
    expect(rows).to_have_count(3)
    expect(p.get_by_test_id("leaves-table").get_by_role("columnheader", name="Actions")).to_have_count(0)
    expect(p.get_by_role("button", name=re.compile(r"^Delete leave"))).to_have_count(0)
    hr.shot("hr-leaves-readonly")


def test_hr_profile_and_analytics(hr, manager_ready, manager_account):
    p = hr.page
    hr.nav("Profile", "/profile")
    prof = p.get_by_test_id("user-profile-page")
    expect(prof).to_contain_text("HR profile")
    expect(prof).to_contain_text("Reports to")
    # HR cannot drill into their manager's profile: plain text, not a link
    expect(prof.get_by_role("link")).to_have_count(0)
    hr.nav("Analytics", "/analytics", "Analytics")
    expect(p.get_by_test_id("analytics-page")).to_contain_text("Your manager's workspace.")
    hr.nav("Account Settings", "/account", "Account Settings")
    expect(p.locator("main")).to_contain_text("HR")


def test_hr_blocked_from_manager_and_admin_urls(hr, manager_ready):
    for path in FORBIDDEN["HR"] + [f"/analysis/{manager_ready['gets_batch_id']}"]:
        hr.expect_denied(path)
    hr.shot("hr-access-denied")
    hr.page.get_by_role("button", name="Back to dashboard").click()
    hr.page.wait_for_url(re.compile(r"/dashboard$"))
    hr.settle()
