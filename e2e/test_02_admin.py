"""Master Admin: every page + every control, account provisioning via the UI."""

import re

from catalog import FORBIDDEN, visit_every_sidebar_page
from conftest import ACCOUNTS, RUN_ID
from playwright.sync_api import expect


def _users_row(page, email):
    return page.get_by_test_id("users-table").locator("tr").filter(has_text=email)


def test_admin_every_sidebar_page(admin):
    visit_every_sidebar_page(admin, "MASTER_ADMIN", "admin")
    admin.nav("Profile", "/profile")
    expect(admin.page.get_by_test_id("user-profile-page")).to_contain_text(admin.email)
    expect(admin.page.get_by_test_id("back-button")).to_have_count(0)
    admin.nav("Dashboard", "/dashboard", "Dashboard")
    for m in ("Employees", "Batches uploaded", "Analysis runs", "Violations detected", "Emails sent"):
        expect(admin.page.get_by_test_id(f"metric-{m}")).to_contain_text(re.compile(r"\d"))
    expect(admin.page.get_by_text("Active accounts by role")).to_be_visible()
    for title, path in (("Manage users", "/users"), ("All GETS uploads", "/all-uploads"), ("Analytics", "/analytics")):
        admin.page.locator("main").get_by_role("link").filter(has_text=title).first.click()
        admin.page.wait_for_url(re.compile(re.escape(path) + "$"))
        admin.settle()
        admin.page.go_back()
        admin.settle()


def test_admin_create_manager_and_executive(admin):
    p = admin.page
    admin.nav("Manage Users", "/users", "Manage Users")

    p.get_by_label("Email").fill("not-an-email")
    p.get_by_test_id("create-user").click()
    expect(p.get_by_text("Enter a valid email")).to_be_visible()

    for role in ("MANAGER", "EXECUTIVE"):
        email = f"e2e.{role.lower()}.{RUN_ID}@example.com"
        name = f"E2E {role.title()} {RUN_ID}"
        p.get_by_label("Full name").fill(name)
        p.get_by_label("Email").fill(email)
        p.locator("select").select_option(role)
        p.get_by_test_id("create-user").click()

        dialog = p.get_by_role("dialog", name="Account created")
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text(email)
        expect(dialog).to_contain_text(role)
        pwd = dialog.get_by_label("Initial password").input_value()
        assert len(pwd) >= 12, "initial password looks too short"
        admin.shot(f"admin-created-{role.lower()}")
        # "Copy" writes the clipboard and auto-closes the one-time dialog
        dialog.get_by_role("button", name="Copy").click()
        expect(dialog).to_be_hidden()
        assert p.evaluate("navigator.clipboard.readText()") == pwd

        row = _users_row(p, email)
        expect(row).to_contain_text(role)
        expect(row).to_contain_text("Active")
        ACCOUNTS[role] = {"email": email, "password": pwd, "name": name, "created_via": "ui"}

    admin.guard.allow(r"^/api/v1/users$", 409, 400, 422, method="POST")
    admin.guard.allow_toast(r".")
    p.get_by_label("Email").fill(ACCOUNTS["MANAGER"]["email"])
    p.get_by_test_id("create-user").click()
    admin.toast("error", re.compile(r".+"))
    expect(p.get_by_role("dialog", name="Account created")).to_have_count(0)


def test_admin_disable_then_enable_user(admin, anon):
    p = admin.page
    admin.goto("/users")
    email = ACCOUNTS["EXECUTIVE"]["email"]
    row = _users_row(p, email)
    row.get_by_role("button", name="Disable").click()
    expect(row).to_contain_text("Disabled")
    expect(row.get_by_role("button", name="Enable")).to_be_visible()
    admin.shot("admin-user-disabled")

    # a disabled account cannot sign in (checked in a separate browser)
    anon.guard.allow(r"^/api/v1/auth/login$", 401, 403, method="POST")
    ap = anon.page
    ap.goto("/login")
    ap.get_by_label("Email").fill(email)
    ap.get_by_label("Password").fill(ACCOUNTS["EXECUTIVE"]["password"])
    ap.get_by_role("button", name="Sign in").click()
    expect(ap.get_by_test_id("login-error")).to_be_visible()
    expect(ap).to_have_url(re.compile(r"/login$"))

    row.get_by_role("button", name="Enable").click()
    expect(row).to_contain_text("Active")
    expect(row.get_by_role("button", name="Disable")).to_be_visible()
    # the admin's own row has no disable button (cannot lock yourself out)
    expect(_users_row(p, admin.email).get_by_role("button")).to_have_count(0)


def test_admin_approve_sso_domain(admin):
    p = admin.page
    admin.goto("/users")
    domain = f"e2e-{RUN_ID}.example.com"
    p.get_by_role("textbox", name="Domain to approve").fill(domain)
    p.get_by_role("button", name="Approve domain").click()
    admin.toast("success", "Domain approved")
    expect(p.get_by_text(domain, exact=True)).to_be_visible()
    expect(p.get_by_role("textbox", name="Domain to approve")).to_have_value("")


def test_admin_drill_down_to_user_profile(admin):
    p = admin.page
    admin.goto("/users")
    mgr = ACCOUNTS["MANAGER"]
    _users_row(p, mgr["email"]).get_by_role("link").click()
    p.wait_for_url(re.compile(r"/people/[0-9a-f-]{36}$"))
    admin.settle()
    page = p.get_by_test_id("user-profile-page")
    expect(page).to_contain_text(mgr["email"])
    expect(page).to_contain_text("Manager")
    expect(p.get_by_test_id("profile-hr-table")).to_be_visible()
    expect(p.get_by_test_id("profile-batches-table")).to_be_visible()
    ACCOUNTS["MANAGER"]["id"] = p.url.rsplit("/", 1)[1]
    admin.shot("admin-people-manager")
    p.get_by_test_id("back-button").click()
    p.wait_for_url(re.compile(r"/users$"))


def test_admin_system_settings_purge(admin):
    p = admin.page
    admin.nav("System Settings", "/settings", "System Settings")
    expect(p.get_by_text(re.compile(r"\d+ days"))).to_be_visible()

    p.once("dialog", lambda d: d.dismiss())
    admin.guard.api_log.clear()
    p.get_by_test_id("purge-button").click()
    p.wait_for_timeout(500)
    assert not [x for x in admin.guard.api_log if "purge" in x[1]]

    messages = []

    def accept(d):
        messages.append(d.message)
        d.accept()

    p.once("dialog", accept)
    p.get_by_test_id("purge-button").click()
    admin.toast("success", re.compile(r"Purged \d+ obsolete batch"))
    assert "older than" in messages[0]
    admin.shot("admin-settings-purged")


def test_admin_audit_logs_filters_export_paging(admin):
    p = admin.page
    admin.nav("Audit Logs", "/audit-logs", "Audit Logs")
    grid = p.locator(".ag-root-wrapper").first
    expect(grid.locator(".ag-row").first).to_be_visible()
    expect(grid).to_contain_text("Success")

    for label, status in (("SUCCESS", "SUCCESS"), ("FAILURE", "FAILURE"), ("DENIED", "DENIED"), ("All", None)):
        btn = p.get_by_role("button", name=label, exact=True)
        btn.click()
        admin.settle()
        expect(btn).to_have_class(re.compile(r"bg-primary-600"))
        if status:
            rows = grid.locator(".ag-row")
            if rows.count():
                statuses = set(grid.locator("[col-id=result] [data-status]").all_inner_texts())
                assert statuses <= {status.title()}, (label, statuses)
            else:
                expect(p.get_by_text("No audit entries match this filter")).to_be_visible()
        admin.shot(f"admin-audit-{label.lower()}")

    # FAILURE rows exist (login test used a wrong password)
    p.get_by_role("button", name="FAILURE", exact=True).click()
    admin.settle()
    expect(grid.locator(".ag-row").first).to_be_visible()
    f = admin.expect_download(lambda: p.get_by_test_id("export-audit").click(), suffix=".csv")
    text = f.read_text()
    assert text.splitlines()[0].lower().startswith(("id", "timestamp")), text[:200]
    assert "FAILURE" in text

    p.get_by_role("button", name="All", exact=True).click()
    admin.settle()
    panel = p.locator(".ag-paging-panel")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text(re.compile(r"1 to \d+ of \d+"))
    panel.get_by_role("combobox", name="Page Size").click()
    p.get_by_role("option", name="20", exact=True).click()
    expect(panel).to_contain_text(re.compile(r"1 to \d+ of \d+"))
    total = int(re.search(r"of (\d+)", panel.inner_text()).group(1))
    if total > 20:  # a fresh database may not have a second page yet
        panel.get_by_role("button", name="Next Page").click()
        expect(panel).to_contain_text(re.compile(r"21 to \d+ of \d+"))
        expect(panel.get_by_role("spinbutton")).to_have_value("2")
        panel.get_by_role("button", name="Previous Page").click()
        expect(panel).to_contain_text(re.compile(r"1 to 20 of \d+"))
    else:
        expect(panel.get_by_role("button", name="Next Page")).to_have_class(re.compile("ag-disabled"))
    admin.shot("admin-audit-paged")
    p.locator(".ag-header-cell[col-id=action]").click()
    expect(p.locator(".ag-header-cell[col-id=action]")).to_have_attribute(
        "aria-sort", re.compile("ascending|descending")
    )


def test_admin_account_settings_and_forbidden_urls(admin):
    p = admin.page
    admin.nav("Account Settings", "/account", "Account Settings")
    expect(p.locator("main")).to_contain_text(admin.email)
    expect(p.locator("main")).to_contain_text("MASTER ADMIN")
    for path in FORBIDDEN["MASTER_ADMIN"]:
        admin.expect_denied(path)
    admin.shot("admin-access-denied")
    p.get_by_role("button", name="Back to dashboard").click()
    p.wait_for_url(re.compile(r"/dashboard$"))
    admin.settle()
