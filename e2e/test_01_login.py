"""Login page + session lifecycle, all through the real form."""

import re

from conftest import ADMIN_EMAIL, ADMIN_PASSWORD
from playwright.sync_api import expect


def test_protected_url_redirects_to_login(anon):
    p = anon.page
    p.goto("/dashboard")
    p.wait_for_url(re.compile(r"/login$"))
    expect(p.get_by_role("heading", name="Welcome back")).to_be_visible()
    anon.shot("01-login-page")
    for path in ("/users", "/gets", "/settings", "/analysis/abc", "/people/xyz"):
        p.goto(path)
        p.wait_for_url(re.compile(r"/login$"))


def test_empty_and_invalid_field_validation(anon):
    p = anon.page
    p.goto("/login")
    p.get_by_role("button", name="Sign in").click()
    expect(p.get_by_text("Enter a valid email address")).to_be_visible()
    expect(p.get_by_label("Email")).to_have_attribute("aria-invalid", "true")

    p.get_by_label("Email").fill("someone@example.com")
    p.get_by_label("Password").fill("short")
    p.get_by_role("button", name="Sign in").click()
    expect(p.get_by_text("Password must be at least 8 characters")).to_be_visible()
    expect(p.get_by_label("Password")).to_have_attribute("aria-invalid", "true")
    anon.shot("02-login-validation")
    # client-side validation must not hit the login endpoint at all
    assert not [x for x in anon.guard.api_log if x[1] == "/api/v1/auth/login"]


def test_wrong_password_shows_error(anon):
    anon.guard.allow(r"^/api/v1/auth/login$", 401, method="POST")
    p = anon.page
    p.goto("/login")
    p.get_by_label("Email").fill(ADMIN_EMAIL)
    p.get_by_label("Password").fill("definitely-Wrong-pass-123")
    p.get_by_role("button", name="Sign in").click()
    err = p.get_by_test_id("login-error")
    expect(err).to_be_visible()
    expect(err).to_have_text(re.compile(r"invalid|incorrect|credentials", re.I))
    expect(p).to_have_url(re.compile(r"/login$"))
    anon.shot("03-login-wrong-password")


def test_login_reload_logout_cycle(anon):
    p = anon.page
    # deep link first: after login the app must return to the requested page
    p.goto("/audit-logs")
    p.wait_for_url(re.compile(r"/login$"))
    p.get_by_label("Email").fill(ADMIN_EMAIL)
    p.get_by_label("Password").fill(ADMIN_PASSWORD)
    anon.guard.logged_in = True
    p.get_by_role("button", name="Sign in").click()
    p.wait_for_url(re.compile(r"/audit-logs$"))
    anon.settle()
    expect(p.locator("main h1")).to_have_text("Audit Logs")

    # session survives a hard reload (refresh-token cookie + rotation)
    anon.guard.api_log.clear()  # drop the pre-login probe (401 by design)
    p.goto("/dashboard")
    anon.settle()
    for _ in range(2):
        p.reload()
        anon.settle()
        expect(p).to_have_url(re.compile(r"/dashboard$"))
        expect(p.get_by_test_id("sidebar")).to_be_attached()
    refreshes = [x for x in anon.guard.api_log if x[1] == "/api/v1/auth/refresh"]
    assert refreshes and all(s == 200 for _, _, s in refreshes), refreshes

    p.goto("/login")
    p.wait_for_url(re.compile(r"/dashboard$"))
    anon.settle()
    anon.shot("04-after-login-dashboard")

    anon.logout()
    expect(p.get_by_role("heading", name="Welcome back")).to_be_visible()
    anon.guard.logged_in = False
    p.goto("/users")
    p.wait_for_url(re.compile(r"/login$"))
    p.reload()
    p.wait_for_url(re.compile(r"/login$"))
    anon.shot("05-after-logout")
