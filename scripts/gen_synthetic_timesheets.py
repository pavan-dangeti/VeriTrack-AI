"""Synthetic timesheet generator for the OCR accuracy tests.

Renders a monthly timesheet page with random invented data (months, fonts, zoom levels, every cell
status), screenshots it with headless Chromium and writes the ground truth next to the images.

    python -m scripts.gen_synthetic_timesheets     # writes test-data/synthetic (git-ignored)
"""

from __future__ import annotations

import argparse
import calendar
import json
import random
from pathlib import Path

# Every name, ID and project below is invented. List lengths are part of the seeded sequence:
# changing them changes every generated sheet (and the fixtures that rely on their IDs and dates).
SURNAMES = ["SAMPLE", "EXAMPLE", "TESTER", "DEMO USER", "PLACEHOLDER", "FICTION",
            "MOCKWELL", "DUMMY", "NOBODY", "ANONYMOUS", "FAKESON", "TRIAL", "SPECIMEN"]
GIVEN = ["ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT", "GOLF", "HOTEL",
         "INDIA", "JULIET", "KILO", "LIMA"]
JOB_FAMILIES = ["Analyst", "Senior Analyst", "Engineer", "Lead Engineer"]
SUB_PROJECTS = ["Onboarding", "Billing API", "Data Pipeline", "Release_24", "Search_v2", "Payments",
                "Mobile App", "Design System", "QA", "Infra_Core", "Analytics", "Docs_Hub",
                "Support", "Migration"]
STATUS_STYLE = {  # fill, text, border
    "REJECTED": ("#DC2626", "#ffffff", "#DC2626"),
    "SUBMITTED": ("#F59E0B", "#1f2937", "#F59E0B"),
    "DRAFT": ("#E2E8F0", "#1f2937", "#94A3B8"),
    "APPROVED": ("#16A34A", "#ffffff", "#16A34A"),
}
FONTS = ["'FreeSans', sans-serif", "'DejaVu Sans', sans-serif", "'Carlito', sans-serif",
         "'Liberation Sans', 'FreeSans', sans-serif"]
WD = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def make_sheet(rng: random.Random) -> dict:
    year = rng.choice([2025, 2026, 2027])
    month = rng.randint(1, 12)
    ndays = calendar.monthrange(year, month)[1]
    weekdays = [d for d in range(1, ndays + 1) if calendar.weekday(year, month, d) < 5]
    person = str(rng.randint(100000, 199999))
    surname, given = rng.choice(SURNAMES), rng.choice(GIVEN)
    name = f"{given.title()} {surname.title()}"
    job = rng.choice(JOB_FAMILIES)

    n_std = rng.randint(1, 7)
    leave_days = sorted(rng.sample(weekdays, rng.randint(0, 4)))
    lines = []
    work_days = [d for d in weekdays if d not in leave_days]
    assignment = {d: rng.randrange(n_std) for d in work_days if rng.random() > 0.08}
    for i in range(n_std):
        days = {}
        for d, owner in assignment.items():
            if owner == i:
                days[d] = rng.choice([8, 8, 8, 8, 7, 6, 5, 4, 9])
        if rng.random() < 0.08:
            wk = [d for d in range(1, ndays + 1) if calendar.weekday(year, month, d) >= 5]
            if wk:
                days[rng.choice(wk)] = rng.choice([4, 8])
        lines.append({
            "uom": "REG", "project_id": str(rng.randint(500000, 599999)),
            "sub_project": rng.choice(SUB_PROJECTS),
            "sub_project_id": str(rng.randint(2000000, 2099999)),
            "days": {str(d): v for d, v in sorted(days.items())},
            "status": rng.choice(list(STATUS_STYLE)),
        })
    if leave_days:
        pos = rng.randint(0, len(lines))
        lines.insert(pos, {
            "uom": "NB", "project_id": str(rng.randint(600000, 699999)),
            "sub_project": "Out Of Office", "sub_project_id": str(rng.randint(2100000, 2199999)),
            "days": {str(d): 8 for d in leave_days},
            "status": rng.choice(["SUBMITTED", "APPROVED"]),
        })
    for ln in lines:
        ln["total"] = sum(ln["days"].values())
    totals = {
        "REG": sum(ln["total"] for ln in lines if ln["uom"] == "REG"),
        "NB": sum(ln["total"] for ln in lines if ln["uom"] == "NB"),
    }
    totals["TOTAL"] = totals["REG"] + totals["NB"]
    return {
        "employee_name": name, "person_id": person, "supplier": "ACME", "job_family": job,
        "month": month, "year": year, "days_in_month": ndays, "lines": lines, "totals": totals,
    }


def render_html(sheet: dict, font: str) -> str:
    y, m, n = sheet["year"], sheet["month"], sheet["days_in_month"]
    day_head = "".join(
        f"<th class='d'>{d}<br><span class='{'we' if calendar.weekday(y, m, d) >= 5 else 'wd'}'>"
        f"{WD[calendar.weekday(y, m, d)]}</span></th>" for d in range(1, n + 1)
    )
    body = []
    for ln in sheet["lines"]:
        bg, fg, border = STATUS_STYLE[ln["status"]]
        cells = []
        for d in range(1, n + 1):
            v = ln["days"].get(str(d))
            style = "" if v is None else f" style='background:{bg};color:{fg};border-color:{border}'"
            cells.append(f"<td class='c'><div class='box'{style}>{'' if v is None else v}</div></td>")
        body.append(
            f"<tr><td>{sheet['person_id']}</td><td>{sheet['supplier']}</td><td>{sheet['job_family']}</td>"
            f"<td class='code'>{ln['uom']}</td><td>{ln['project_id']}</td><td class='sp'>{ln['sub_project']}</td>"
            f"<td>{ln['sub_project_id']}</td><td></td>{''.join(cells)}<td class='tot'>{ln['total']}</td></tr>"
        )

    def totals_row(label, kind):
        rows = [ln for ln in sheet["lines"] if kind in (None, ln["uom"])]
        vals = "".join(f"<td class='tv'>{sum(ln['days'].get(str(d), 0) for ln in rows)}</td>" for d in range(1, n + 1))
        grand = sheet["totals"]["TOTAL" if kind is None else kind]
        return f"<tr class='trow'><td colspan='8' class='lbl'>{label}</td>{vals}<td class='tv tot'>{grand}</td></tr>"

    return f"""<!doctype html><html><head><style>
body{{margin:0;background:#ffffff;font-family:{font};font-variant-ligatures:none;color:#1f2937;width:1880px}}
.app{{background:#1e293b;color:#f8fafc;height:56px;display:flex;align-items:center;padding-left:24px;
font-size:22px;font-weight:bold;letter-spacing:1px}}
.who{{margin:22px 0 18px 24px;font-size:17px;line-height:30px}}
.who span{{display:inline-block;width:110px;color:#64748b}}
table{{border-collapse:collapse;margin-left:24px;font-size:14px}}
th,td{{border:1px solid #e2e8f0;padding:4px 6px;white-space:nowrap}}
th{{font-weight:600;background:#ffffff;color:#334155;text-align:left}}
th.d{{text-align:center;width:32px;font-size:13px}}
.wd{{color:#64748b;font-weight:normal}} .we{{color:#ea580c;font-weight:normal}}
td.c{{padding:3px 3px}}
.box{{width:32px;height:22px;border:1px solid #94a3b8;border-radius:3px;background:#fff;text-align:center;
line-height:22px;font-size:14px}}
td.code{{font-weight:600;color:#334155}}
td.sp{{max-width:96px;white-space:normal}}
td.tv{{text-align:center}} td.lbl{{text-align:right;font-weight:600;color:#334155}} td.tot{{font-weight:600}}
.legend{{display:flex;gap:44px;margin:28px 0 0 24px;font-size:14px;color:#334155}}
.sw{{display:inline-block;width:18px;height:14px;margin-right:10px;vertical-align:middle;border-radius:3px}}
</style></head><body>
<div class='app'>Timesheet</div>
<div class='who'><div><span>Employee</span><b>{sheet['employee_name']}</b></div>
<div><span>Period</span><b>{calendar.month_name[m]} {y}</b></div></div>
<table><tr><th>Employee ID</th><th>Client</th><th>Role</th><th>Type</th><th>Project Code</th><th>Task</th>
<th>Task Code</th><th>Notes</th>{day_head}<th>Total</th></tr>
{''.join(body)}
{totals_row('Total REG', 'REG')}
{totals_row('Total NB', 'NB')}
{totals_row('Grand total', None)}
</table>
<div class='legend'>{''.join(
    f"<span><span class='sw' style='background:{STATUS_STYLE[k][0]}'></span>{k.title()}</span>"
    for k in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED"))}</div>
<div style='height:40px'></div></body></html>"""


DEFAULT_DIR = Path(__file__).resolve().parents[1] / "test-data" / "synthetic"
DEFAULT_COUNT = 16
DEFAULT_SEED = 4242


def generate(out: Path, count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED) -> Path:
    import os

    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)  # noqa: S311 — test data, not crypto
    truth = {}
    with sync_playwright() as p:
        exe = os.environ.get("CHROMIUM_PATH")
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        for i in range(count):
            sheet = make_sheet(rng)
            font = FONTS[i % len(FONTS)]
            zoom = [1.0, 1.25, 1.0, 1.5, 0.9, 1.1][i % 6]
            page = browser.new_page(viewport={"width": 1900, "height": 800}, device_scale_factor=zoom)
            page.set_content(render_html(sheet, font))
            name = f"synthetic_{i:03d}.png"
            page.screenshot(path=str(out / name), full_page=True)
            page.close()
            truth[name] = sheet
        browser.close()
    (out / "ground_truth.json").write_text(json.dumps(truth, indent=1))
    return out


def ensure(out: Path = DEFAULT_DIR) -> Path | None:
    """The sheets are generated on first use and never committed. Returns the
    folder, or None when Playwright/Chromium is not available."""
    if (out / "ground_truth.json").exists():
        return out
    try:
        return generate(out)
    except Exception:  # noqa: BLE001 — no browser: callers skip
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_DIR))
    ap.add_argument("--count", type=int, default=DEFAULT_COUNT)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args()
    out = generate(Path(args.out), args.count, args.seed)
    print(f"wrote {args.count} sheets to {out}")


if __name__ == "__main__":
    main()
