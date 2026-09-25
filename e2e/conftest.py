"""Real-browser (Playwright/Chromium) end-to-end harness.

Each logical user gets one RoleSession that logs in once through the real form, so refresh-token
rotation is exercised and the login rate limit is never hit. Every page carries a Guard that fails
the test on page errors, console errors, 5xx or unexpected 4xx responses; tests that provoke a 4xx
declare it with ``guard.allow(...)``.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import pytest
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    expect,
    sync_playwright,
)
from playwright.sync_api import TimeoutError as PWTimeout

REPO = pathlib.Path(__file__).resolve().parent.parent
BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:5173").rstrip("/")
SHOTS = pathlib.Path(os.environ.get("E2E_SHOTS_DIR", REPO / "e2e" / ".artifacts"))
CHROMIUM = os.environ.get("E2E_CHROMIUM") or None  # None = Playwright's own Chromium
HEADLESS = os.environ.get("E2E_HEADED", "") == ""
RUN_ID = time.strftime("%m%d%H%M%S")  # unique suffix => reruns never collide

SYNTH = REPO / "test-data" / "synthetic"  # generated on first use, never committed
GETS_SHEETS = {  # file -> person id (see tests/test_timesheet_leave_flow.py)
    "synthetic_000.png": "103729",
    "synthetic_004.png": "158082",
    "synthetic_007.png": "141220",
    "synthetic_013.png": "197061",
}
EXPECTED_VIOLATIONS = {"141220": "2025-07-28", "197061": "2025-06-18"}

REPO_CSV = b"""Employee ID,Full Name,Company Email,Personal Email,Dept
103729,Golf Anonymous,golf.anonymous@example.com,,Eng
158082,Kilo Specimen,kilo.specimen@example.com,,Eng
141220,Bravo Example,,bravo.example@example.net,Eng
197061,Echo Specimen,echo.specimen@example.com,,Eng
"""

LEAVE_CSV = b"""Employee ID,From Date,To Date,Leave Type
103729,09-03-2026,,Casual
103729,2026-03-24,,Casual
141220,01/07/2025,01/07/2025,Sick
141220,03-Jul-2025,,Casual
141220,2025-07-14,,Casual
197061,02-Jun-2025,03-Jun-2025,Earned
197061,11/06/2025,,Casual
"""


def _ensure_synthetic() -> None:
    import sys

    sys.path.insert(0, str(REPO))
    from scripts.gen_synthetic_gets import ensure

    ensure(SYNTH)


_ensure_synthetic()


def _dotenv() -> dict[str, str]:
    env: dict[str, str] = {}
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


_ENV = _dotenv()
# Explicit env vars win; the repo's .env seed values are a local-dev fallback.
ADMIN_EMAIL = os.environ.get("E2E_ADMIN_EMAIL") or _ENV.get("SEED_ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.environ.get("E2E_ADMIN_PASSWORD") or _ENV.get("SEED_ADMIN_PASSWORD", "")

ACCOUNTS: dict[str, dict[str, str]] = {}
FACTS: dict[str, object] = {}


_SKIP_REASON: str | None = None


def _probe() -> str | None:
    import urllib.error
    import urllib.request

    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        return "E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD not set (and no SEED_ADMIN_* in .env)"
    try:
        urllib.request.urlopen(BASE_URL + "/", timeout=5).read(1)  # noqa: S310
    except Exception as exc:  # noqa: BLE001
        return f"frontend not reachable at {BASE_URL}: {exc}"
    try:
        req = urllib.request.Request(BASE_URL + "/api/v1/auth/csrf", method="POST")  # noqa: S310
        urllib.request.urlopen(req, timeout=5).read(1)  # noqa: S310
    except Exception as exc:  # noqa: BLE001
        return f"API not reachable through {BASE_URL}/api: {exc}"
    if CHROMIUM and not pathlib.Path(CHROMIUM).exists():
        return f"Chromium not found at {CHROMIUM} (set E2E_CHROMIUM)"
    return None


def pytest_collection_modifyitems(config, items):
    global _SKIP_REASON
    _SKIP_REASON = _probe()
    if _SKIP_REASON:
        marker = pytest.mark.skip(reason=f"E2E suite skipped: {_SKIP_REASON}")
        for item in items:
            item.add_marker(marker)


NOISE = re.compile(
    r"ERR_TUNNEL_CONNECTION_FAILED|fonts\.googleapis|fonts\.gstatic|ERR_PROXY|"
    r"Failed to load resource: net::ERR_(NAME_NOT_RESOLVED|INTERNET_DISCONNECTED)",
    re.I,
)


@dataclass
class Allowance:
    path_re: re.Pattern
    statuses: set[int]
    method: str | None = None

    def matches(self, method: str, path: str, status: int) -> bool:
        return (
            status in self.statuses
            and (self.method is None or self.method == method)
            and bool(self.path_re.search(path))
        )


# Allowed for every session, always. Each one is a deliberate app behaviour:
PERMANENT_ALLOWANCES = [
    # ReportsPage / AnalysisResults probe `GET /batches/:id/analysis`; the API
    # answers 404 for a batch that has never been analysed (the UI then shows
    # "no analysis yet" or keeps polling while a run starts).
    Allowance(re.compile(r"^/api/v1/batches/[^/]+/analysis$"), {404}, "GET"),
]


@dataclass
class Guard:
    label: str
    logged_in: bool = False
    errors: list[str] = field(default_factory=list)
    allowances: list[Allowance] = field(default_factory=list)
    api_log: list[tuple[str, str, int]] = field(default_factory=list)

    toast_allowances: list[re.Pattern] = field(default_factory=list)

    def allow_toast(self, text_regex: str) -> None:
        self.toast_allowances.append(re.compile(text_regex, re.I))

    def on_toast(self, kind: str, text: str) -> None:
        if kind != "error":
            return
        if any(r.search(text) for r in self.toast_allowances):
            return
        self.errors.append(f"[{self.label}] unexpected error toast: {text!r}")

    def allow(self, path_regex: str, *statuses: int, method: str | None = None) -> None:
        self.allowances.append(Allowance(re.compile(path_regex), set(statuses), method))

    def reset(self) -> None:
        self.errors.clear()
        self.allowances.clear()
        self.toast_allowances.clear()
        self.api_log.clear()

    def on_console(self, msg) -> None:
        if msg.type != "error":
            return
        text = msg.text
        url = (msg.location or {}).get("url", "") or ""
        if NOISE.search(text) or NOISE.search(url):
            return
        if text.startswith("Failed to load resource") and urlparse(url).path.startswith("/api/"):
            return  # judged precisely by on_response (status + allowances)
        self.errors.append(f"[{self.label}] console.error: {text} @ {url}")

    def on_pageerror(self, err) -> None:
        self.errors.append(f"[{self.label}] uncaught page error: {err}")

    def on_response(self, resp) -> None:
        path = urlparse(resp.url).path
        if not path.startswith("/api/"):
            if resp.status >= 400 and urlparse(resp.url).netloc == urlparse(BASE_URL).netloc:
                self.errors.append(f"[{self.label}] asset {resp.status}: {resp.url}")
            return
        method = resp.request.method
        status = resp.status
        self.api_log.append((method, path, status))
        if status < 400:
            return
        if status >= 500:
            self.errors.append(f"[{self.label}] SERVER ERROR {status} {method} {path}: {_body(resp)}")
            return
        # pre-login session probe: no refresh cookie yet
        if not self.logged_in and path == "/api/v1/auth/refresh" and status == 401:
            return
        for a in PERMANENT_ALLOWANCES + self.allowances:
            if a.matches(method, path, status):
                return
        self.errors.append(f"[{self.label}] unexpected {status} {method} {path}: {_body(resp)}")

    def on_requestfailed(self, req) -> None:
        if NOISE.search(req.url) or NOISE.search(req.failure or ""):
            return
        path = urlparse(req.url).path
        # navigation / unmount aborts are normal for in-flight polls
        if (req.failure or "").startswith("net::ERR_ABORTED"):
            return
        if path.startswith("/api/"):
            self.errors.append(f"[{self.label}] request failed {req.method} {path}: {req.failure}")


def _body(resp) -> str:
    try:
        return resp.text()[:300]
    except Exception:  # noqa: BLE001
        return "<no body>"


LIVE_SESSIONS: list[RoleSession] = []

TOAST_OBSERVER_JS = """
(() => {
  const seen = new WeakSet();
  const report = (el) => {
    if (seen.has(el)) return;
    seen.add(el);
    try { window.__e2eToast('error', (el.textContent || '').trim()); } catch (e) {}
  };
  const scan = (node) => {
    if (!(node instanceof Element)) return;
    if (node.matches('[data-testid="toast-error"]')) report(node);
    node.querySelectorAll('[data-testid="toast-error"]').forEach(report);
  };
  new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach(scan)))
    .observe(document, { childList: true, subtree: true });
})();
"""


class RoleSession:
    def __init__(self, browser: Browser, label: str, *, viewport=None, **ctx_kwargs):
        self.label = label
        self.context: BrowserContext = browser.new_context(
            base_url=BASE_URL,
            accept_downloads=True,
            locale="en-US",
            timezone_id="UTC",
            viewport=viewport or {"width": 1440, "height": 900},
            permissions=["clipboard-read", "clipboard-write"],
            **ctx_kwargs,
        )
        self.context.set_default_timeout(15_000)
        self.guard = Guard(label)
        self.context.expose_binding("__e2eToast", lambda _src, kind, text: self.guard.on_toast(kind, text))
        self.context.add_init_script(TOAST_OBSERVER_JS)
        self.page: Page = self.context.new_page()
        self._attach(self.page)
        self.email: str | None = None
        LIVE_SESSIONS.append(self)

    def _attach(self, page: Page) -> None:
        page.on("console", self.guard.on_console)
        page.on("pageerror", self.guard.on_pageerror)
        page.on("response", self.guard.on_response)
        page.on("requestfailed", self.guard.on_requestfailed)

    def close(self) -> None:
        if self in LIVE_SESSIONS:
            LIVE_SESSIONS.remove(self)
        try:
            self.context.close()
        except Exception:  # noqa: BLE001
            pass

    def login(self, email: str, password: str) -> None:
        p = self.page
        # let the app's session probe finish before a 401 on it counts as a bug
        with p.expect_response(lambda r: r.url.endswith("/api/v1/auth/refresh")):
            p.goto("/login")
        expect(p.get_by_role("heading", name="Welcome back")).to_be_visible()
        p.get_by_label("Email").fill(email)
        p.get_by_label("Password").fill(password)
        self.guard.logged_in = True  # from here on a refresh 401 is a bug
        p.get_by_role("button", name="Sign in").click()
        p.wait_for_url(re.compile(r"/dashboard$"), timeout=20_000)
        expect(p.get_by_test_id("sidebar")).to_be_attached()
        self.email = email
        self.settle()

    def logout(self) -> None:
        self.page.get_by_test_id("logout").click()
        self.page.wait_for_url(re.compile(r"/login"))
        self.guard.logged_in = False

    def settle(self, timeout: int = 15_000) -> None:
        p = self.page
        try:
            p.wait_for_load_state("networkidle", timeout=4_000)
        except PWTimeout:
            pass  # pages that poll never go idle; the skeleton check decides
        expect(p.get_by_test_id("skeleton")).to_have_count(0, timeout=timeout)
        expect(p.get_by_test_id("analysis-running")).to_have_count(0, timeout=timeout)

    def goto(self, path: str) -> None:
        self.page.goto(path)
        self.settle()

    def nav(self, label: str, expect_path: str, heading: str | None = None) -> None:
        p = self.page
        link = p.get_by_role("navigation", name="Main navigation").get_by_role("link", name=label, exact=True)
        link.click()
        p.wait_for_url(re.compile(re.escape(expect_path) + r"$"))
        self.settle()
        expect(link).to_have_class(re.compile(r"(^|\s)text-white(\s|$)"))
        if heading:
            expect(p.locator("main h1").first).to_have_text(heading)

    def shot(self, name: str) -> pathlib.Path:
        d = SHOTS / self.label
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{name}.png"
        try:
            self.page.screenshot(path=str(path), full_page=True, animations="disabled")
        except Exception:  # noqa: BLE001 — screenshots never fail a test
            pass
        return path

    def sidebar_labels(self) -> list[str]:
        nav = self.page.get_by_role("navigation", name="Main navigation")
        return [t.strip() for t in nav.get_by_role("link").all_inner_texts()]

    def expect_download(self, click, min_bytes: int = 1, suffix: str | None = None) -> pathlib.Path:
        with self.page.expect_download(timeout=30_000) as dl_info:
            click()
        dl = dl_info.value
        assert dl.failure() is None, f"download failed: {dl.failure()}"
        target = SHOTS / self.label / "downloads" / dl.suggested_filename
        target.parent.mkdir(parents=True, exist_ok=True)
        dl.save_as(str(target))
        size = target.stat().st_size
        assert size >= min_bytes, f"download {dl.suggested_filename} is {size} bytes"
        if suffix:
            assert dl.suggested_filename.endswith(suffix), dl.suggested_filename
        return target

    def toast(self, kind: str, text: str | re.Pattern, timeout: int = 15_000):
        loc = self.page.get_by_test_id(f"toast-{kind}").filter(has_text=text)
        expect(loc.first).to_be_visible(timeout=timeout)
        return loc.first

    def expect_denied(self, path: str) -> None:
        p = self.page
        p.goto(path)
        p.wait_for_url(re.compile(r"/access-denied$"))
        expect(p.get_by_role("heading", name="Access denied")).to_be_visible()
        expect(p.get_by_test_id("denied-path")).to_contain_text(path)


def grid_filter(page, col_id: str, text: str) -> None:
    """Type into an AG Grid column's text filter (header filter button)."""
    page.locator(f".ag-header-cell[col-id={col_id}] .ag-header-cell-filter-button").click()
    flt = page.locator(".ag-filter").first
    expect(flt).to_be_visible()
    flt.locator("input[type=text], input:not([type])").first.fill(text)
    page.keyboard.press("Escape")
    expect(flt).to_be_hidden()


def api_login(pw: Playwright, email: str, password: str):
    req = pw.request.new_context(base_url=BASE_URL)
    r = req.post("/api/v1/auth/login", data={"email": email, "password": password})
    assert r.ok, f"api login failed {r.status}: {r.text()}"
    token = r.json()["access_token"]
    return req, {"Authorization": f"Bearer {token}"}


def api_create_user(pw: Playwright, creator: dict, email: str, role: str) -> dict:
    req, h = api_login(pw, creator["email"], creator["password"])
    r = req.post("/api/v1/users", data={"email": email, "role": role, "full_name": None}, headers=h)
    assert r.status == 201, r.text()
    body = r.json()
    req.dispose()
    return {"email": email, "password": body["initial_password"], "id": body["user"]["id"]}


@pytest.fixture(scope="session")
def pw():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(pw) -> Browser:
    b = pw.chromium.launch(
        executable_path=CHROMIUM,
        headless=HEADLESS,
        # keep Chromium's own background services (autofill, sync, updates) quiet
        args=[
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--disable-features=AutofillServerCommunication,OptimizationHints,MediaRouter",
        ],
    )
    yield b
    for s in list(LIVE_SESSIONS):
        s.close()
    b.close()


@pytest.fixture(scope="session")
def admin_account() -> dict:
    ACCOUNTS.setdefault("MASTER_ADMIN", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    return ACCOUNTS["MASTER_ADMIN"]


def _ensure(pw, role: str, creator: dict) -> dict:
    if role not in ACCOUNTS:
        email = f"e2e.{role.lower()}.{RUN_ID}@example.com"
        ACCOUNTS[role] = api_create_user(pw, creator, email, role)
        ACCOUNTS[role]["created_via"] = "api-fallback"
    return ACCOUNTS[role]


@pytest.fixture(scope="session")
def manager_account(pw, admin_account) -> dict:
    return _ensure(pw, "MANAGER", admin_account)


@pytest.fixture(scope="session")
def executive_account(pw, admin_account) -> dict:
    return _ensure(pw, "EXECUTIVE", admin_account)


@pytest.fixture(scope="session")
def hr_account(pw, manager_account) -> dict:
    return _ensure(pw, "HR", manager_account)


def _session_fixture(label: str, account_fixture: str):
    @pytest.fixture(scope="session")
    def _fx(browser, request) -> RoleSession:
        acct = request.getfixturevalue(account_fixture)
        s = RoleSession(browser, label)
        s.login(acct["email"], acct["password"])
        yield s
        s.close()

    return _fx


admin = _session_fixture("admin", "admin_account")
manager = _session_fixture("manager", "manager_account")
executive = _session_fixture("executive", "executive_account")
hr = _session_fixture("hr", "hr_account")


@pytest.fixture
def anon(browser) -> RoleSession:
    s = RoleSession(browser, "anon")
    yield s
    s.close()


@pytest.fixture(scope="session")
def manager_ready(manager_account, pw):
    """Guarantees the manager has repo + leave + an analysed GETS batch (via the API if test_03 did not run)."""
    if FACTS.get("gets_batch_id") and FACTS.get("analysed"):
        return FACTS
    req, h = api_login(pw, manager_account["email"], manager_account["password"])

    def up(kind, files):
        r = req.post(f"/api/v1/uploads?kind={kind}", multipart={"files": files}, headers=h)
        assert r.status == 201, r.text()
        return r.json()["id"]

    def wait(bid):
        for _ in range(240):
            b = req.get(f"/api/v1/uploads/batches/{bid}", headers=h).json()
            if b["status"] in ("COMPLETED", "FAILED"):
                return b
            time.sleep(1)
        raise AssertionError("batch never finished")

    wait(up("EMPLOYEE_REPO", {"name": "repo.csv", "mimeType": "text/csv", "buffer": REPO_CSV}))
    wait(up("COMPANY_LEAVE", {"name": "leave.csv", "mimeType": "text/csv", "buffer": LEAVE_CSV}))
    # multipart with several files under one field: use the raw form API
    form = [("files", (n, (SYNTH / n).read_bytes(), "image/png")) for n in GETS_SHEETS]
    import urllib.request

    boundary = "----e2e" + RUN_ID
    body = b""
    for name, (fn, data, ct) in form:
        body += (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{fn}"\r\n'
                f"Content-Type: {ct}\r\n\r\n"
            ).encode()
            + data
            + b"\r\n"
        )
    body += f"--{boundary}--\r\n".encode()
    r = urllib.request.Request(  # noqa: S310
        BASE_URL + "/api/v1/uploads?kind=GETS",
        data=body,
        headers={**h, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    bid = json.loads(urllib.request.urlopen(r).read())["id"]  # noqa: S310
    wait(bid)
    rr = req.post(f"/api/v1/batches/{bid}/analyze", headers=h)
    assert rr.status == 202, rr.text()
    for _ in range(120):
        a = req.get(f"/api/v1/batches/{bid}/analysis", headers=h)
        if a.ok and a.json()["status"] != "RUNNING":
            break
        time.sleep(1)
    FACTS["gets_batch_id"] = bid
    FACTS["analysed"] = True
    req.dispose()
    return FACTS


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    # errors raised between tests (fixture setup, background polls) count
    # against the next test, so nothing slips through unobserved.
    outcome = yield
    problems = [e for s in LIVE_SESSIONS for e in s.guard.errors]
    for s in LIVE_SESSIONS:
        s.guard.reset()
    if problems and outcome.excinfo is None:
        outcome.force_exception(AssertionError("Browser/network errors during test:\n  " + "\n  ".join(problems)))
    elif problems:
        print("Also recorded browser/network errors:\n  " + "\n  ".join(problems))
