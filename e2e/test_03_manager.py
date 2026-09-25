"""Manager: the full compliance workflow, entirely through the UI.

repository upload -> leave register (upload / add / filter / delete) ->
GETS upload with live progress -> per-sheet review -> analysis (double-click
safe) -> results with the two expected violations -> exports/reports ->
HR account creation -> dashboard numbers.
"""

import re

from catalog import FORBIDDEN, visit_every_sidebar_page
from conftest import (
    ACCOUNTS,
    EXPECTED_VIOLATIONS,
    FACTS,
    GETS_SHEETS,
    LEAVE_CSV,
    REPO_CSV,
    RUN_ID,
    SYNTH,
)
from playwright.sync_api import expect


def test_manager_first_login_lands_on_dashboard(manager, manager_account):
    p = manager.page
    # First login of a freshly provisioned account: the app has no forced
    # password-change step, the user lands straight on the dashboard.
    expect(p).to_have_url(re.compile(r"/dashboard$"))
    expect(p.locator("main h1")).to_have_text("Dashboard")
    expect(p.get_by_test_id("profile-link")).to_contain_text("Manager")
    expect(p.get_by_test_id("metric-Employees").locator("p.text-3xl")).to_have_text("0")
    manager.shot("manager-00-first-login")
    visit_every_sidebar_page(manager, "MANAGER", "manager-empty")
    manager.nav("GETS Uploads", "/gets", "GETS Uploads")
    expect(p.get_by_text("No GETS uploads yet")).to_be_visible()
    manager.nav("Reports & History", "/reports", "Reports & History")
    expect(p.get_by_text("No GETS batches yet")).to_be_visible()
    manager.nav("Employee Repository", "/employees", "Employee Repository")
    expect(p.get_by_text("No employees uploaded yet")).to_be_visible()


def test_manager_employee_repository_upload_filter_detail(manager):
    p = manager.page
    manager.nav("Employee Repository", "/employees", "Employee Repository")
    p.get_by_test_id("repo-upload-input").set_input_files(
        files=[{"name": f"repo-{RUN_ID}.csv", "mimeType": "text/csv", "buffer": REPO_CSV}]
    )
    manager.toast("success", re.compile(r"Uploaded 1 file"))
    manager.toast("success", "Repository upload processed", timeout=60_000)

    grid = p.get_by_test_id("employees-grid")
    for code in ("103729", "158082", "141220", "197061"):
        expect(grid.get_by_text(code, exact=True)).to_be_visible(timeout=30_000)
    expect(grid.locator(".ag-row:has([col-id=employee_code])")).to_have_count(4)
    manager.shot("manager-employees-uploaded")

    p.get_by_test_id("tab-needs-review").click()
    expect(p.get_by_text("Nothing awaiting review")).to_be_visible()
    p.get_by_role("tab", name="All employees").click()
    expect(grid.locator(".ag-row:has([col-id=employee_code])")).to_have_count(4)

    p.locator(".ag-header-cell[col-id=full_name] .ag-header-cell-filter-button").click()
    flt = p.locator(".ag-filter").first
    expect(flt).to_be_visible()
    flt.locator("input[type=text], input:not([type])").first.fill("Bravo")
    expect(grid.locator(".ag-row:has([col-id=employee_code])")).to_have_count(1)
    expect(grid).to_contain_text("Bravo Example")
    manager.shot("manager-employees-filtered")
    flt.locator("input[type=text], input:not([type])").first.fill("")
    p.keyboard.press("Escape")
    expect(grid.locator(".ag-row:has([col-id=employee_code])")).to_have_count(4)

    p.locator(".ag-header-cell[col-id=employee_code] .ag-header-cell-text").click()
    expect(p.locator(".ag-header-cell[col-id=employee_code]")).to_have_attribute("aria-sort", "ascending")
    first = grid.locator(".ag-row[row-index='0'] [col-id=employee_code]")
    expect(first).to_have_text("103729")

    grid.get_by_role("link", name="141220").click()
    p.wait_for_url(re.compile(r"/employees/[0-9a-f-]{36}$"))
    manager.settle()
    detail = p.get_by_test_id("employee-detail-page")
    expect(detail.locator("h1")).to_have_text("Bravo Example")
    expect(detail).to_contain_text("Employee 141220")
    expect(detail).to_contain_text("bravo.example@example.net")
    expect(p.get_by_test_id("employee-versions-table").locator("tbody tr")).to_have_count(1)
    manager.shot("manager-employee-detail")
    p.get_by_test_id("back-button").click()
    p.wait_for_url(re.compile(r"/employees$"))


def _leave_rows(p):
    return p.get_by_test_id("leaves-table").locator("tbody tr")


def test_manager_leave_register_upload_add_filter_delete(manager):
    p = manager.page
    manager.nav("Company Leave Register", "/leaves", "Company Leave Register")
    p.get_by_test_id("leave-file-input").set_input_files(
        files=[{"name": f"leave-{RUN_ID}.csv", "mimeType": "text/csv", "buffer": LEAVE_CSV}]
    )
    manager.toast("info", "Register queued")
    manager.toast("success", "Leave register upload processed", timeout=60_000)

    month = p.get_by_test_id("leave-month")
    month.fill("2025-06")
    expect(_leave_rows(p)).to_have_count(3)  # range 2-3 expanded + 11
    expect(p.get_by_text("3 day(s)")).to_be_visible()
    expect(p.get_by_text("June 2025")).to_be_visible()
    month.fill("2025-07")
    expect(_leave_rows(p)).to_have_count(3)
    month.fill("2026-03")
    expect(_leave_rows(p)).to_have_count(2)
    month.fill("")
    p.get_by_role("textbox", name="Employee ID").fill("197061")
    expect(_leave_rows(p)).to_have_count(3)
    p.get_by_role("textbox", name="Employee ID").fill("")
    expect(_leave_rows(p)).to_have_count(8)
    manager.shot("manager-leaves-all")

    # manual entry through the modal (unrelated employee => analysis unaffected)
    p.get_by_test_id("add-leave").click()
    dlg = p.get_by_role("dialog", name="Add company leave")
    expect(dlg).to_be_visible()
    expect(dlg.get_by_test_id("save-leave")).to_be_disabled()
    dlg.get_by_label("Employee ID").fill("999001")
    dlg.get_by_label("From").fill("2025-06-20")
    dlg.get_by_label("To (optional)").fill("2025-06-21")
    dlg.get_by_label("Leave type (optional)").fill("Casual")
    manager.shot("manager-leave-add-modal")
    dlg.get_by_test_id("save-leave").click()
    manager.toast("success", "2 leave day(s) added")
    expect(dlg).to_be_hidden()
    month.fill("2025-06")
    expect(_leave_rows(p)).to_have_count(5)
    row = _leave_rows(p).filter(has_text="999001")
    expect(row).to_have_count(2)
    expect(row.first).to_contain_text("Manual")

    p.get_by_test_id("add-leave").click()
    dlg.get_by_role("button", name="Cancel").click()
    expect(dlg).to_be_hidden()
    p.get_by_test_id("add-leave").click()
    expect(dlg).to_be_visible()
    p.keyboard.press("Escape")
    expect(dlg).to_be_hidden()

    for day in ("2025-06-20", "2025-06-21"):
        p.get_by_role("button", name=f"Delete leave {day} for 999001").click()
        manager.toast("success", "Leave entry removed")
        expect(p.get_by_role("button", name=f"Delete leave {day} for 999001")).to_have_count(0)
    expect(_leave_rows(p)).to_have_count(3)
    manager.shot("manager-leaves-june")


def _batch_card(p):
    return p.locator("[data-testid^='batch-']").first


def test_manager_gets_upload_progress_and_sheet_review(manager):
    p = manager.page
    manager.nav("GETS Uploads", "/gets", "GETS Uploads")
    p.get_by_test_id("gets-file-input").set_input_files([str(SYNTH / n) for n in GETS_SHEETS])
    manager.toast("info", "4 file(s) queued")

    card = _batch_card(p)
    expect(card).to_be_visible()
    batch_id = card.get_attribute("data-testid").removeprefix("batch-")
    FACTS["gets_batch_id"] = batch_id
    expect(card.get_by_role("progressbar")).to_be_visible()
    expect(card.get_by_test_id("inspect")).to_have_attribute("aria-expanded", "true")
    manager.shot("manager-gets-processing")

    seen = set()
    counter = card.get_by_text(re.compile(r"\d/4 files processed"))
    for _ in range(360):
        seen.add(counter.inner_text())
        if card.locator("[data-status=COMPLETED]").count():
            break
        p.wait_for_timeout(500)
    expect(card.locator("[data-status=COMPLETED]").first).to_be_visible(timeout=5_000)
    expect(counter).to_have_text("4/4 files processed")
    expect(card.get_by_role("progressbar")).to_have_attribute("aria-valuenow", "100")
    manager.toast("success", "GETS batch processed", timeout=10_000)
    print("progress states observed:", sorted(seen))

    files = card.get_by_test_id("progress-card").locator("tbody tr")
    expect(files).to_have_count(4)
    for i in range(4):
        row = files.nth(i)
        expect(row.locator("[data-status=DONE]")).to_be_visible()
        expect(row.get_by_text(re.compile(r"Totals verified|auto-corrected"))).to_be_visible()
    manager.shot("manager-gets-completed")

    f = manager.expect_download(
        lambda: card.get_by_role("button", name="Export").click(), min_bytes=1000, suffix=".xlsx"
    )
    assert f.read_bytes()[:2] == b"PK"

    names = list(GETS_SHEETS)
    for name in names:
        manager.goto("/gets")
        card = _batch_card(p)
        card.get_by_test_id("inspect").click()
        row = card.get_by_test_id("progress-card").locator("tbody tr").filter(has_text=name)
        row.get_by_role("button", name="Review").click()
        p.wait_for_url(re.compile(rf"/review/{batch_id}/[0-9a-f-]{{36}}$"))
        manager.settle()
        page = p.get_by_test_id("sheet-review-page")
        expect(page.locator("h1")).to_have_text(name)
        expect(page).to_contain_text(f"ID {GETS_SHEETS[name]}")
        img = p.get_by_role("img", name="Uploaded GETS sheet")
        expect(img).to_be_visible()
        p.wait_for_function(
            "() => { const i = document.querySelector('img[alt=\"Uploaded GETS sheet\"]');"
            " return i && i.complete && i.naturalWidth > 0; }"
        )
        grid = p.get_by_test_id("timesheet-grid")
        expect(grid).to_be_visible()
        expect(grid.locator("tbody tr").first).to_be_visible()
        checks = p.get_by_test_id("checks")
        expect(checks.locator("li").first).to_be_visible()
        expect(checks.get_by_label("failed")).to_have_count(0)
        expect(p.get_by_text(re.compile(r"Verification \((\d+)/\1 passed\)"))).to_be_visible()
        stem = name.removesuffix(".png")
        manager.shot(f"manager-review-{stem}-split")
        p.get_by_role("tab", name="Grid").click()
        expect(grid).to_be_visible()
        expect(img).to_have_count(0)
        manager.shot(f"manager-review-{stem}-grid")
        p.get_by_role("tab", name="Original").click()
        expect(p.get_by_test_id("timesheet-grid")).to_have_count(0)
        expect(p.get_by_role("img", name="Uploaded GETS sheet")).to_be_visible()
        p.get_by_role("tab", name="Side by side").click()
        expect(p.get_by_test_id("timesheet-grid")).to_be_visible()
        p.get_by_test_id("back-button").click()
        p.wait_for_url(re.compile(r"/gets$"))
        manager.settle()

    card = _batch_card(p)
    card.get_by_test_id("inspect").click()
    card.get_by_test_id("progress-card").get_by_role("button", name="Re-extract").first.click()
    manager.toast("success", "Re-extraction complete", timeout=90_000)
    expect(card.get_by_test_id("progress-card").locator("[data-status=DONE]")).to_have_count(4)
    card.get_by_test_id("inspect").click()
    expect(card.get_by_test_id("progress-card")).to_have_count(0)


def test_manager_run_analysis_double_click_and_results(manager):
    p = manager.page
    batch_id = FACTS["gets_batch_id"]
    manager.goto("/gets")
    # A double-click must not start two runs. The second request, if it gets
    # out at all, is refused as already analysed (409) or rate-limited.
    manager.guard.allow(rf"^/api/v1/batches/{batch_id}/analyze$", 409, method="POST")
    btn = p.get_by_test_id(f"analyze-{batch_id}")
    expect(btn).to_have_text("Run analysis")
    btn.dblclick()
    p.wait_for_url(re.compile(rf"/analysis/{batch_id}$"))
    manager.settle(timeout=120_000)
    posts = [x for x in manager.guard.api_log if x[0] == "POST" and x[1].endswith("/analyze")]
    assert len(posts) == 1, f"double-click sent {len(posts)} analyze requests: {posts}"
    assert posts[0][2] == 202, posts

    page = p.get_by_test_id("analysis-page")
    expect(page).to_be_visible()
    expect(page.locator("h1")).to_have_text("Analysis results")

    def stat(label):
        return (
            page.locator("div.rounded-2xl")
            .filter(has=p.locator("p", has_text=re.compile(rf"^{label}$")))
            .first.locator("p.text-3xl")
        )

    expect(stat("Violations")).to_have_text("2")
    expect(stat("Employees checked")).to_have_text(re.compile(r"^[1-9]\d*$"))
    table = p.get_by_test_id("violations-table")
    rows = table.locator("tbody tr")
    expect(rows).to_have_count(2)
    for code, date in EXPECTED_VIOLATIONS.items():
        row = rows.filter(has_text=code)
        expect(row).to_have_count(1)
        # the missing register day is the red badge in column 3
        month_day = {"2025-07-28": "Jul 28", "2025-06-18": "Jun 18"}[date]
        expect(row.locator("td").nth(2)).to_have_text(month_day)
    expect(table).not_to_contain_text("103729")
    expect(table).not_to_contain_text("158082")
    manager.shot("manager-analysis-results")
    FACTS["analysed"] = True

    pdf = manager.expect_download(
        lambda: p.get_by_role("button", name="Summary PDF").click(), min_bytes=500, suffix=".pdf"
    )
    assert pdf.read_bytes()[:4] == b"%PDF"
    xlsx = manager.expect_download(
        lambda: p.get_by_role("button", name="Excel report").click(), min_bytes=1000, suffix=".xlsx"
    )
    assert xlsx.read_bytes()[:2] == b"PK"

    manager.goto("/gets")
    manager.guard.allow(rf"^/api/v1/batches/{batch_id}/analyze$", 409, method="POST")
    p.get_by_test_id(f"analyze-{batch_id}").click()
    p.wait_for_url(re.compile(rf"/analysis/{batch_id}$"))
    manager.settle()
    expect(p.get_by_test_id("violations-table").locator("tbody tr")).to_have_count(2)
    p.get_by_role("button", name="Back").click()
    p.wait_for_url(re.compile(r"/gets$"))


def test_manager_reports_history(manager):
    p = manager.page
    manager.nav("Reports & History", "/reports", "Reports & History")
    rows = p.locator("main").locator("div.rounded-2xl").filter(has=p.get_by_role("button", name="Summary PDF"))
    expect(rows).to_have_count(1)  # exactly one run, even after the double-click
    row = rows.first
    expect(row).to_contain_text("2 violations")
    manager.shot("manager-reports")
    manager.expect_download(lambda: row.get_by_role("button", name="Summary PDF").click(), min_bytes=500, suffix=".pdf")
    manager.expect_download(
        lambda: row.get_by_role("button", name="3-tab Excel").click(), min_bytes=1000, suffix=".xlsx"
    )
    # "Resend" is exercised in test_09
    row.get_by_role("button", name="View results").click()
    p.wait_for_url(re.compile(r"/analysis/[0-9a-f-]{36}$"))
    manager.settle()
    expect(p.get_by_test_id("violations-table").locator("tbody tr")).to_have_count(2)


def test_manager_creates_hr_account(manager):
    p = manager.page
    manager.nav("My HR Team", "/hr-team", "My HR Team")
    expect(p.get_by_text("No HR accounts yet.")).to_be_visible()
    p.get_by_role("button", name="Create HR account").click()
    expect(p.get_by_text("Enter a valid email")).to_be_visible()

    email = f"e2e.hr.{RUN_ID}@example.com"
    p.get_by_label("Full name").fill(f"E2E Hr {RUN_ID}")
    p.get_by_label("HR email").fill(email)
    p.get_by_role("button", name="Create HR account").click()
    dlg = p.get_by_role("dialog", name="Account created")
    expect(dlg).to_contain_text(email)
    expect(dlg).to_contain_text("HR")
    pwd = dlg.get_by_label("Initial password").input_value()
    assert len(pwd) >= 12
    manager.shot("manager-hr-created")
    dlg.get_by_role("button", name="Close").click()
    expect(dlg).to_be_hidden()
    ACCOUNTS["HR"] = {"email": email, "password": pwd, "created_via": "ui"}

    table = p.get_by_test_id("hr-team-table")
    expect(table).to_contain_text(email)
    table.get_by_role("link").first.click()
    p.wait_for_url(re.compile(r"/people/[0-9a-f-]{36}$"))
    manager.settle()
    prof = p.get_by_test_id("user-profile-page")
    expect(prof).to_contain_text("HR profile")
    expect(prof).to_contain_text("Reports to")
    manager.shot("manager-hr-profile")
    p.get_by_test_id("back-button").click()
    p.wait_for_url(re.compile(r"/hr-team$"))


def test_manager_dashboard_numbers_analytics_profile(manager):
    p = manager.page
    manager.nav("Dashboard", "/dashboard", "Dashboard")
    p.reload()  # summary is cached 15s; force fresh numbers
    manager.settle()

    def metric(name):
        return p.get_by_test_id(f"metric-{name}").locator("p.text-3xl")

    expect(metric("Employees")).to_have_text("4")
    expect(metric("Batches uploaded")).to_have_text(re.compile(r"^[1-9]\d*$"))
    expect(metric("Analysis runs")).to_have_text("1")  # the double-click made one run
    expect(metric("Violations detected")).to_have_text("2")
    expect(metric("Emails sent")).to_have_text(re.compile(r"^\d+$"))
    manager.shot("manager-dashboard-populated")
    for title, path in (
        ("Upload GETS sheets", "/gets"),
        ("Update leave register", "/leaves"),
        ("Employee repository", "/employees"),
    ):
        p.locator("main").get_by_role("link").filter(has_text=title).click()
        p.wait_for_url(re.compile(re.escape(path) + "$"))
        manager.settle()
        p.go_back()
        manager.settle()

    manager.nav("Analytics", "/analytics", "Analytics")
    ap = p.get_by_test_id("analytics-page")
    expect(ap).to_contain_text("Your workspace only.")
    expect(ap.locator(".recharts-surface").first).to_be_visible()
    manager.shot("manager-analytics")

    manager.nav("Profile", "/profile")
    prof = p.get_by_test_id("user-profile-page")
    expect(prof).to_contain_text("Manager profile")
    expect(p.get_by_test_id("profile-hr-table")).to_contain_text(ACCOUNTS["HR"]["email"])
    expect(p.get_by_test_id("profile-batches-table").locator("tbody tr")).to_have_count(1)
    manager.shot("manager-profile")


def test_manager_forbidden_urls(manager):
    for path in FORBIDDEN["MANAGER"]:
        manager.expect_denied(path)
    manager.page.get_by_role("button", name="Back to dashboard").click()
    manager.page.wait_for_url(re.compile(r"/dashboard$"))
    manager.settle()
