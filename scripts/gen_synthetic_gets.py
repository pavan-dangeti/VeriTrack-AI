"""Synthetic GETS timesheet generator for the accuracy regression tests.

Renders an HTML replica of the GETS "Time Sheet" page with random invented data (months, fonts,
zoom levels, every cell status), screenshots it with headless Chromium and writes the ground truth.

    python -m scripts.gen_synthetic_gets     # writes test-data/synthetic (git-ignored)
"""

from __future__ import annotations

import argparse
import calendar
import json
import random
from pathlib import Path

# Every name, ID and project below is invented; no real person or project.
SURNAMES = ["SAMPLE", "EXAMPLE", "TESTER", "DEMO USER", "PLACEHOLDER", "FICTION",
            "MOCKWELL", "DUMMY", "NOBODY", "ANONYMOUS", "FAKESON", "TRIAL", "SPECIMEN"]
GIVEN = ["ALPHA", "BRAVO", "C", "D", "ECHO", "FOXTROT", "GOLF", "HOTEL",
         "INDIA", "JULIET", "KILO", "LIMA"]
JOB_FAMILIES = ["Analyst", "Analyst - Senior", "Engineer", "Design Engineer - Lead"]
SUB_PROJECTS = ["Alpha", "Bravo Mesh", "Core Unit", "P100_Model", "Q200_Mesh", "AlphaMesh",
                "Charlie Frame", "Delta", "EFG", "XY_Mesh", "Gamma CAE", "Om_Model",
                "Durability", "Panel Trim"]
STATUS_STYLE = {
    "USER_SIGNED": ("#C2367A", "#ffffff", "#C2367A"),
    "PM_APPROVED": ("#FFF9D0", "#212529", "#b9b39a"),
    "LM_APPROVED": ("#E4E4E4", "#212529", "#a0a0a0"),
    "PLANNED": ("#5B78C7", "#ffffff", "#5B78C7"),
}
FONTS = ["'FreeSans'", "'DejaVu Sans'", "'Carlito'", "'Liberation Sans', 'FreeSans'"]
WD = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def make_sheet(rng: random.Random) -> dict:
    year = rng.choice([2025, 2026, 2027])
    month = rng.randint(1, 12)
    ndays = calendar.monthrange(year, month)[1]
    weekdays = [d for d in range(1, ndays + 1) if calendar.weekday(year, month, d) < 5]
    person = str(rng.randint(100000, 199999))
    surname, given = rng.choice(SURNAMES), rng.choice(GIVEN)
    name = f"{surname}, {given} ({given[0]}.)"
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
            "uom": "STD", "project_id": str(rng.randint(500000, 599999)),
            "sub_project": rng.choice(SUB_PROJECTS),
            "sub_project_id": str(rng.randint(2000000, 2099999)),
            "days": {str(d): v for d, v in sorted(days.items())},
            "status": rng.choice(list(STATUS_STYLE)),
        })
    if leave_days:
        pos = rng.randint(0, len(lines))
        lines.insert(pos, {
            "uom": "NC", "project_id": str(rng.randint(600000, 699999)),
            "sub_project": "Out Of Office", "sub_project_id": str(rng.randint(2100000, 2199999)),
            "days": {str(d): 8 for d in leave_days},
            "status": rng.choice(["USER_SIGNED", "PM_APPROVED"]),
        })
    for ln in lines:
        ln["total"] = sum(ln["days"].values())
    totals = {
        "NC": sum(ln["total"] for ln in lines if ln["uom"] == "NC"),
        "STD": sum(ln["total"] for ln in lines if ln["uom"] == "STD"),
    }
    totals["TOTAL"] = totals["NC"] + totals["STD"]
    return {
        "employee_name": name, "person_id": person, "supplier": "ACME", "job_family": job,
        "month": month, "year": year, "days_in_month": ndays, "lines": lines, "totals": totals,
    }


def render_html(sheet: dict, font: str) -> str:
    y, m, n = sheet["year"], sheet["month"], sheet["days_in_month"]
    day_head = "".join(
        f"<th class='d'><b>{d}</b><br><span class='{'we' if calendar.weekday(y, m, d) >= 5 else 'wd'}'>"
        f"{WD[calendar.weekday(y, m, d)]}</span></th>" for d in range(1, n + 1)
    )
    body = []
    for ln in sheet["lines"]:
        bg, fg, border = STATUS_STYLE[ln["status"]]
        cells = []
        for d in range(1, n + 1):
            v = ln["days"].get(str(d))
            if v is None:
                cells.append("<td class='c'><div class='box'></div></td>")
            else:
                cells.append(
                    f"<td class='c'><div class='box' style='background:{bg};color:{fg};"
                    f"border-color:{border}'>{v}</div></td>"
                )
        body.append(
            "<tr><td class='sel'><input type='checkbox'></td>"
            f"<td><span class='dd'>{sheet['person_id']} <i>&#8964;</i></span></td>"
            f"<td>{sheet['supplier']}</td><td>{sheet['job_family']}</td>"
            f"<td><span class='dd uom'>{ln['uom']} <i>&#8964;</i></span></td>"
            f"<td>{ln['project_id']}</td><td class='sp'>{ln['sub_project']}{' -' if ln['uom'] == 'NC' else ''}</td>"
            f"<td>{ln['sub_project_id']}</td><td><a>Remark</a></td>{''.join(cells)}"
            f"<td class='tot'>{ln['total']}</td></tr>"
        )
    def totals_row(label, kind):
        vals = []
        for d in range(1, n + 1):
            s = sum(ln["days"].get(str(d), 0) for ln in sheet["lines"] if kind in (None, ln["uom"]))
            vals.append(f"<td class='tv'>{s}</td>")
        grand = sheet["totals"]["TOTAL" if kind is None else kind]
        return (f"<tr class='trow'><td colspan='8' class='lbl'>{label}</td><td class='k'>"
                f"{kind or 'Total'}</td>{''.join(vals)}<td class='tv'>{grand}</td></tr>")

    return f"""<!doctype html><html><head><style>
body{{margin:0;background:#f3f4f6;font-family:{font};font-variant-ligatures:none;color:#212529;width:1880px}}
.top{{display:flex;align-items:center;background:#f8f9fa;height:118px}}
.burger{{width:120px;text-align:center;font-size:26px}}
.logo{{width:135px;height:118px;background:#13206e;color:#fff;font-weight:bold;font-size:20px;
display:flex;align-items:flex-end;justify-content:center;letter-spacing:3px}}
.title{{padding-left:12px}} .title h1{{font-size:30px;font-weight:normal;margin:6px 0 16px}}
.title .g{{font-size:19px}}
.nav{{display:flex;gap:40px;align-items:center;background:#eef0f2;height:44px;padding-left:50px;margin-top:8px}}
.nav .b{{background:#2233b8;color:#fff;padding:7px 18px;border-radius:3px;font-size:19px}}
.bar{{display:flex;justify-content:space-between;padding:14px 12px}}
.btn{{background:#2233b8;color:#fff;padding:9px 12px;border-radius:4px;font-size:15px}}
.right{{display:flex;gap:18px;margin-right:260px;margin-top:10px}}
.sel2{{background:#2233b8;color:#fff;padding:6px 8px;border-radius:4px;font-size:18px;min-width:40px}}
table{{border-collapse:collapse;margin-left:14px;font-size:14px;background:#f3f4f6}}
th,td{{border:1px solid #dee2e6;padding:3px 4px;white-space:nowrap}}
th{{font-weight:bold}} th.d{{text-align:center;width:26px;font-size:14px}}
.wd{{color:#777;font-weight:normal}} .we{{color:#e0102a;font-weight:normal}}
td.c{{padding:3px 3px}}
.box{{width:26px;height:21px;border:1px solid #9a9a9a;background:#fff;text-align:center;
line-height:21px;font-size:14px}}
.dd{{color:#999;border:1px solid #e3e3e3;padding:1px 4px}} .dd i{{font-style:normal;font-size:11px}}
.uom{{display:inline-block;width:56px}}
td.sp{{max-width:84px;white-space:normal}}
a{{color:#1a55d6;text-decoration:underline}}
td.tv{{text-align:center}} td.lbl{{text-align:right;border-right:none}} td.k{{font-weight:bold;border-left:none}}
.legend{{display:flex;gap:60px;margin:40px 0 0 500px;font-size:14px}}
.sw{{display:inline-block;width:24px;height:20px;margin-right:40px;vertical-align:middle}}
</style></head><body>
<div class='top'><div class='burger'>&#9776;</div><div class='logo'>GETS</div>
<div class='title'><h1>Welcome to <b>GETS - Efforts Tracking System</b></h1>
<div class='g'>Good Day, <b>{sheet['employee_name']}</b></div></div></div>
<div class='nav'><span>Home</span><span class='b'>Time Sheet</span><span>Help &#9662;</span></div>
<div class='bar'><span class='btn'>Add Project</span><div class='right'><span class='btn'>Delete Project</span>
<span class='sel2'>{y} &#8964;</span>
<span class='sel2' style='min-width:90px'>{calendar.month_name[m]} &#8964;</span></div></div>
<table><tr><th>Select<br><input type='checkbox'></th><th>Person ID</th><th>Supplier</th>
<th>Billable Job Family</th><th>UOM</th><th>Project ID</th><th>Sub Project</th><th>Sub Project ID</th>
<th>Remarks</th>{day_head}<th>Total</th></tr>
{''.join(body)}
{totals_row('Totals per Project Hour Type', 'NC')}
{totals_row('Totals per Project Hour Type', 'STD')}
{totals_row('', None)}
</table>
<div class='legend'><span><span class='sw' style='background:#5B78C7'></span>Planned</span>
<span><span class='sw' style='background:#C2367A'></span>User Signed</span>
<span><span class='sw' style='background:#FFF9D0'></span>PM Approved</span>
<span><span class='sw' style='background:#E4E4E4'></span>LM Approved</span></div>
<div style='height:60px'></div></body></html>"""


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
