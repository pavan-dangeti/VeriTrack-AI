"""App-shell features: sidebar, theme, command palette, mobile, 404."""

import re

from catalog import SIDEBAR
from conftest import RoleSession
from playwright.sync_api import expect


def test_sidebar_collapse_expand_persists(manager):
    p = manager.page
    manager.goto("/dashboard")
    side = p.get_by_test_id("sidebar")
    expect(side).to_have_class(re.compile(r"\bw-64\b"))
    p.get_by_role("button", name="Collapse sidebar").click()
    expect(side).to_have_class(re.compile(r"w-\[72px\]"))
    # compact: icon-only links with a tooltip title, still navigable
    link = side.locator("a[title='Company Leave Register']")
    expect(link).to_be_visible()
    expect(link).to_have_text("")
    manager.shot("shell-sidebar-collapsed")
    p.reload()
    manager.settle()
    expect(side).to_have_class(re.compile(r"w-\[72px\]"))
    link.click()
    p.wait_for_url(re.compile(r"/leaves$"))
    manager.settle()
    p.get_by_role("button", name="Expand sidebar").click()
    expect(side).to_have_class(re.compile(r"\bw-64\b"))
    p.reload()
    manager.settle()
    expect(side).to_have_class(re.compile(r"\bw-64\b"))
    assert manager.sidebar_labels() == [x[0] for x in SIDEBAR["MANAGER"]]


def test_theme_toggle_persists_after_reload(manager):
    p = manager.page
    manager.goto("/dashboard")
    html = p.locator("html")
    expect(html).not_to_have_class(re.compile(r"\bdark\b"))
    p.get_by_test_id("theme-toggle").click()
    expect(html).to_have_class(re.compile(r"\bdark\b"))
    expect(p.get_by_role("button", name="Switch to light theme")).to_be_visible()
    p.reload()
    manager.settle()
    expect(html).to_have_class(re.compile(r"\bdark\b"))
    for path in ("/dashboard", "/gets", "/leaves", "/employees", "/reports"):
        manager.goto(path)
        manager.shot(f"shell-dark{path.replace('/', '-')}")
    bg = p.evaluate("getComputedStyle(document.querySelector('div.min-h-screen')).backgroundColor")
    assert bg not in ("rgb(255, 255, 255)", "rgba(0, 0, 0, 0)"), bg
    p.get_by_test_id("theme-toggle").click()
    expect(html).not_to_have_class(re.compile(r"\bdark\b"))
    p.reload()
    manager.settle()
    expect(html).not_to_have_class(re.compile(r"\bdark\b"))


def test_command_palette_keyboard_and_mouse(manager):
    p = manager.page
    manager.goto("/dashboard")
    pal = p.get_by_role("dialog", name="Command palette")

    p.keyboard.press("Control+k")
    expect(pal).to_be_visible()
    search = pal.get_by_role("textbox", name="Search pages")
    expect(search).to_be_focused()
    expect(pal.get_by_role("option")).to_have_count(len(SIDEBAR["MANAGER"]))
    search.fill("leave")
    expect(pal.get_by_role("option")).to_have_count(1)
    expect(pal.get_by_role("option").first).to_contain_text("Company Leave Register")
    manager.shot("shell-palette-filtered")
    p.keyboard.press("Enter")
    p.wait_for_url(re.compile(r"/leaves$"))
    expect(pal).to_be_hidden()
    manager.settle()

    # hint text is searchable too ("timesheets" is in the GETS hint)
    p.keyboard.press("Control+k")
    search.fill("timesheets")
    expect(pal.get_by_role("option").first).to_contain_text("GETS Uploads")
    search.fill("zzzz-nothing")
    expect(pal.get_by_text("No matches")).to_be_visible()
    p.keyboard.press("Escape")
    expect(pal).to_be_hidden()

    p.get_by_test_id("open-palette").click()
    expect(pal).to_be_visible()
    expect(pal.get_by_role("option").nth(0)).to_have_attribute("aria-selected", "true")
    p.keyboard.press("ArrowDown")
    p.keyboard.press("ArrowDown")
    expect(pal.get_by_role("option").nth(2)).to_have_attribute("aria-selected", "true")
    p.keyboard.press("ArrowUp")
    expect(pal.get_by_role("option").nth(1)).to_have_attribute("aria-selected", "true")
    p.keyboard.press("Enter")
    p.wait_for_url(re.compile(r"/analytics$"))
    manager.settle()

    p.keyboard.press("Control+k")
    expect(pal).to_be_visible()
    p.keyboard.press("Control+k")
    expect(pal).to_be_hidden()
    p.keyboard.press("Control+k")
    p.mouse.click(10, 10)
    expect(pal).to_be_hidden()
    p.keyboard.press("Control+k")
    pal.get_by_role("option").filter(has_text="My HR Team").click()
    p.wait_for_url(re.compile(r"/hr-team$"))
    manager.settle()


def test_unknown_routes_redirect(manager, anon):
    p = manager.page
    for bad in ("/this-page-does-not-exist", "/gets/extra/segments/x", "/dashboard/nope"):
        p.goto(bad)
        p.wait_for_url(re.compile(r"/dashboard$"))
        manager.settle()
    anon.page.goto("/definitely/not/here")
    anon.page.wait_for_url(re.compile(r"/login$"))


def _no_horizontal_scroll(page):
    sw, cw = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    assert sw <= cw, f"horizontal scroll on {page.url}: scrollWidth {sw} > clientWidth {cw}"


def test_mobile_viewport_drawer_and_layout(browser, manager_account, manager_ready):
    s = RoleSession(browser, "mobile", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    try:
        s.login(manager_account["email"], manager_account["password"])
        p = s.page
        expect(p.get_by_test_id("sidebar")).to_be_hidden()
        open_btn = p.get_by_role("button", name="Open menu")
        expect(open_btn).to_be_visible()
        _no_horizontal_scroll(p)
        s.shot("mobile-dashboard")

        open_btn.click()
        close_btn = p.get_by_role("button", name="Close menu")
        expect(close_btn).to_be_visible()
        s.shot("mobile-drawer-open")
        drawer = close_btn.locator("xpath=..")
        drawer.get_by_role("link", name="Company Leave Register").click()
        p.wait_for_url(re.compile(r"/leaves$"))
        expect(close_btn).to_be_hidden()
        s.settle()
        _no_horizontal_scroll(p)
        s.shot("mobile-leaves")

        open_btn.click()
        expect(close_btn).to_be_visible()
        close_btn.click()
        expect(close_btn).to_be_hidden()
        open_btn.click()
        expect(close_btn).to_be_visible()
        p.mouse.click(380, 400)
        expect(close_btn).to_be_hidden()

        for path in (
            "/gets",
            "/employees",
            "/reports",
            "/hr-team",
            "/profile",
            "/account",
            "/analytics",
            f"/analysis/{manager_ready['gets_batch_id']}",
        ):
            s.goto(path)
            expect(p.locator("main h1").first).to_be_visible()
            _no_horizontal_scroll(p)
            s.shot(f"mobile{path.replace('/', '-')[:40]}")
    finally:
        s.close()
