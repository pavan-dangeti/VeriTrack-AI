"""'Resend' reports — runs last because it currently breaks later downloads."""

from playwright.sync_api import expect


def _report_card(p, bid):
    return p.locator("main div.rounded-2xl").filter(has=p.locator(f"a[href='/analysis/{bid}']"))


def test_resend_reports_then_download_again(manager, executive, manager_ready):
    bid = manager_ready["gets_batch_id"]

    ep = executive.page
    executive.goto("/all-reports")
    _report_card(ep, bid).get_by_role("button", name="Resend").click()
    executive.toast("success", "Reports re-delivered")

    p = manager.page
    manager.goto("/reports")
    card = _report_card(p, bid)
    expect(card).to_have_count(1)
    card.get_by_role("button", name="Resend").click()
    manager.toast("success", "Reports re-delivered")
    manager.shot("manager-reports-resent")

    # Downloads must keep working after a resend.
    with p.expect_response(lambda r: r.url.endswith("/reports/summary.pdf")) as resp_info:
        manager.expect_download(
            lambda: card.get_by_role("button", name="Summary PDF").click(), min_bytes=500, suffix=".pdf"
        )
    assert resp_info.value.status == 200
    manager.expect_download(
        lambda: card.get_by_role("button", name="3-tab Excel").click(), min_bytes=1000, suffix=".xlsx"
    )
    expect(p.get_by_test_id("toast-error")).to_have_count(0)
