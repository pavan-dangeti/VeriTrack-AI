"""Negative / edge cases through the UI: bad uploads, bad URLs, stress."""

import io
import random
import re

from catalog import SIDEBAR
from conftest import RUN_ID, SYNTH
from PIL import Image
from playwright.sync_api import expect


def _upload_rejected(session, files, status, message_re):
    p = session.page
    session.guard.allow(r"^/api/v1/uploads$", status, method="POST")
    session.guard.allow_toast(message_re)
    before = p.locator("[data-testid^='batch-']").count()
    p.get_by_test_id("gets-file-input").set_input_files(files)
    session.toast("error", re.compile(message_re, re.I))
    expect(p.get_by_text("Drop GETS screenshots here or click to browse")).to_be_visible()
    expect(p.locator("[data-testid^='batch-']")).to_have_count(before)


def test_gets_rejects_non_image_and_garbage_files(manager):
    manager.goto("/gets")
    _upload_rejected(
        manager,
        [{"name": "notes.txt", "mimeType": "text/plain", "buffer": b"hello, not a timesheet"}],
        400,
        r"allowed types",
    )
    manager.shot("neg-gets-txt-rejected")
    _upload_rejected(
        manager,
        [{"name": "fake.png", "mimeType": "image/png", "buffer": bytes(random.Random(1).randbytes(4096))}],
        415,
        r"fake\.png",
    )
    manager.shot("neg-gets-fake-png-rejected")
    _upload_rejected(
        manager,
        [{"name": "empty.png", "mimeType": "image/png", "buffer": b""}],
        400,
        r"is empty",
    )
    png = (SYNTH / "synthetic_000.png").read_bytes()
    _upload_rejected(
        manager,
        [{"name": f"s{i}.png", "mimeType": "image/png", "buffer": png} for i in range(21)],
        400,
        r"Maximum 20 files",
    )


def test_repository_rejects_garbage(manager):
    p = manager.page
    manager.goto("/employees")
    manager.guard.allow(r"^/api/v1/uploads$", 400, 415, method="POST")
    manager.guard.allow_toast(r".")
    p.get_by_test_id("repo-upload-input").set_input_files(
        [{"name": "bad.exe", "mimeType": "application/octet-stream", "buffer": b"MZ\x90\x00garbage"}]
    )
    manager.toast("error", re.compile(r"allowed types", re.I))
    expect(p.get_by_test_id("upload-repo")).to_be_enabled()
    expect(p.get_by_test_id("employees-grid")).to_be_visible()


def test_non_gets_image_ends_failed_or_needs_review(manager):
    p = manager.page
    manager.goto("/gets")
    rnd = random.Random(42)
    img = Image.new("RGB", (900, 500))
    img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(900 * 500)])
    buf = io.BytesIO()
    img.save(buf, "PNG")
    # the batch watcher toasts "GETS batch failed (1 file)" — expected here
    manager.guard.allow_toast(r"GETS batch failed")
    p.get_by_test_id("gets-file-input").set_input_files(
        [{"name": f"noise-{RUN_ID}.png", "mimeType": "image/png", "buffer": buf.getvalue()}]
    )
    manager.toast("info", "1 file(s) queued")
    card = p.locator("[data-testid^='batch-']").first
    expect(card.locator("[data-status=COMPLETED], [data-status=FAILED]").first).to_be_visible(timeout=120_000)
    row = card.get_by_test_id("progress-card").locator("tbody tr").first
    expect(row).to_contain_text(f"noise-{RUN_ID}.png")
    # the batch badge and the per-file rows refresh on separate polls
    expect(row.locator("[data-status]").first).to_have_attribute("data-status", "FAILED", timeout=15_000)
    status = row.locator("[data-status]").first.get_attribute("data-status")
    manager.shot("neg-gets-noise-image")
    assert status == "FAILED", status
    msg = row.locator("p.text-danger-700")
    expect(msg).to_contain_text("No timesheet found")
    expect(card.get_by_text("1 failed")).to_be_visible()
    expect(card.get_by_role("button", name="Re-extract")).to_be_visible()


def test_bad_drilldown_urls_render_friendly_states(manager):
    p = manager.page
    manager.guard.allow(r"^/api/v1/uploads/batches/[^/]+/files/[^/]+/extraction$", 404, 422, method="GET")
    manager.guard.allow(r"^/api/v1/employees/[^/]+/detail$", 404, 422, method="GET")
    manager.guard.allow(r"^/api/v1/users/[^/]+/profile$", 403, 404, 422, method="GET")
    manager.goto("/review/not-a-uuid/also-bad")
    expect(p.get_by_text("Extraction not available")).to_be_visible()
    manager.goto("/review/00000000-0000-0000-0000-000000000000/00000000-0000-0000-0000-000000000000")
    expect(p.get_by_text("Extraction not available")).to_be_visible()
    manager.goto("/employees/00000000-0000-0000-0000-000000000000")
    expect(p.get_by_text("Employee unavailable")).to_be_visible()
    manager.goto("/people/00000000-0000-0000-0000-000000000000")
    expect(p.get_by_text("Profile unavailable")).to_be_visible()
    manager.shot("neg-bad-urls")


def test_rapid_navigation_between_pages(manager):
    p = manager.page
    manager.goto("/dashboard")
    nav = p.get_by_role("navigation", name="Main navigation")
    labels = [x[0] for x in SIDEBAR["MANAGER"]]
    for _ in range(3):
        for label in labels:
            nav.get_by_role("link", name=label, exact=True).click()  # no waiting in between
        for label in reversed(labels):
            nav.get_by_role("link", name=label, exact=True).click()
    p.wait_for_url(re.compile(r"/dashboard$"))
    manager.settle()
    expect(p.locator("main h1")).to_have_text("Dashboard")
    p.go_back()
    p.wait_for_url(re.compile(r"/analytics$"))
    manager.settle()
    expect(p.locator("main h1")).to_have_text("Analytics")
    p.go_forward()
    p.wait_for_url(re.compile(r"/dashboard$"))
    manager.settle()
