"""Live demo: full VeriTrack flow on deliberately messy data.

Run with API up:  uvicorn app.main:app --port 8000
Then:             python scripts/demo_messy_flow.py

Demonstrates: repo upload -> GETS batch (3 messy files incl. real XLSX) ->
analyze -> violation dedup -> email resolution (dry-run) -> report artifacts.
"""

import io
import sys

import httpx
from openpyxl import Workbook, load_workbook

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

REPO_CSV = """Employee ID,Full Name,Company Email,Personal Email,Dept
E-100,Ann Weaver,ann.weaver@corp.io,ann.w@gmail.com,
E-200,Bob Chen,,bob.chen@gmail.com,Sales
E-300,Cid Reyes,,,HR
E-400,Dia Patel,dia.patel@corp.io,,Finance
E-500,Evan Wright,evan@corp.io,evan.w@gmail.com,Ops
E-600,Faith Khan,faith.khan@corp.io,,Legal
E-700,Gus Ortiz,gus@corp.io,gus.o@gmail.com,
E-800,Hana Lee,hana.lee@corp.io,,Design
"""

# Messy: inconsistent ticks, whitespace, dashes, dupes across files, ghosts.
GETS_A_CSV = """EMP CODE,Emp Name,Customer Leave,Sacha Leave
E-100,Ann Weaver,✓,
E-200,Bob Chen,X,✓
E-999,Ghost Person,✔,
   ,   ,YES ,
E-300,Cid Reyes,YES,-
E-500,Evan Wright,[x],
E-600,Faith Khan,x,y
"""

GETS_B_CSV = """Employee ID,Name,Customer Leave,Sacha Leave
E-100,Ann Weaver,x,
E-700,Gus Ortiz,true,false
E-800,Hana Lee,,✓
E-4O0,Zero Instead Of O,✓,
"""


def build_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "July GETS"
    ws.append([" Emp Code ", " Employee Name ", " Department ", " Customer Leave ",
               " Sacha Leave "])
    rows = [
        ["E-200", "Bob Chen", "Sales", "✓", ""],          # violation, personal email
        ["E-400", "Dia Patel", "", "yes", "no"],          # violation, official email
        ["E-500", "Evan Wright", "Ops", "✓", "✓"],        # both ticked -> clean
    ]
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=60)

    # --- bootstrap MA if needed, then create a fresh manager -----------------
    r = c.post("/api/v1/auth/login", json={
        "email": "admin@veritrack.io", "password": "Bootstrap!Pass123"})
    assert r.status_code == 200, f"MA login failed: {r.text}"
    ma = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = c.post("/api/v1/users", json={
        "email": "demo.manager@veritrack.io", "role": "MANAGER"}, headers=ma)
    if r.status_code == 409:  # demo rerun
        print("Manager exists from previous run; continuing (repo already loaded)")
        mgr_pw = None
    else:
        assert r.status_code == 201, r.text
        mgr_pw = r.json()["initial_password"]
    if mgr_pw is None:
        print("NOTE: previous demo state detected; results below are cumulative.\n")
        return

    r = c.post("/api/v1/auth/login", json={
        "email": "demo.manager@veritrack.io", "password": mgr_pw})
    m = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # --- 1. one-time employee repository -------------------------------------
    r = c.post("/api/v1/uploads?kind=EMPLOYEE_REPO",
               files=[("files", ("employee_master.csv",
                                 io.BytesIO(REPO_CSV.encode()), "text/csv"))], headers=m)
    print(f"[1] repository upload      -> {r.status_code} batch={r.json()['status']} "
          f"(8 employees)")

    # --- 2. GETS batch: 2 CSVs + 1 real XLSX ----------------------------------
    files = [
        ("files", ("gets_july_a.csv", io.BytesIO(GETS_A_CSV.encode()), "text/csv")),
        ("files", ("gets_july_b.csv", io.BytesIO(GETS_B_CSV.encode()), "text/csv")),
        ("files", ("gets_july_sheet.xlsx", io.BytesIO(build_xlsx()),
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ]
    r = c.post("/api/v1/uploads?kind=GETS", files=files, headers=m)
    batch = r.json()
    print(f"[2] GETS batch upload      -> {r.status_code} status={batch['status']} "
          f"files={batch['total_files']}")

    detail = c.get(f"/api/v1/uploads/batches/{batch['id']}", headers=m).json()
    for f in detail["files"]:
        print(f"      {f['original_filename']:22} {f['content_type_detected'] or '?':58} "
              f"{f['status']:5} rows={f['rows_extracted']}")

    # --- 3. analyze ------------------------------------------------------------
    r = c.post(f"/api/v1/batches/{batch['id']}/analyze", headers=m)
    result = r.json()
    print(f"[3] analyze                -> {r.status_code}")
    print(f"      rows_processed={result.get('rows_processed')} "
          f"matched={result.get('matched')} violations={result.get('violations')} "
          f"emails_sent={result.get('emails_sent')} skipped={result.get('skipped')}")

    # --- 4. results -------------------------------------------------------------
    analysis = c.get(f"/api/v1/batches/{batch['id']}/analysis", headers=m).json()
    t = analysis["totals"]
    print("\n=== VIOLATIONS (deduped per employee) ===")
    for v in analysis["violations"]:
        print(f"  {v['employee_code']:6} {(v['employee_name'] or ''):14} "
              f"{v['email_status']:16} -> {v['email_to'] or '—'}")
    print("\n=== SKIPPED / NOT PROCESSED ===")
    for s in analysis["skipped_rows"]:
        print(f"  {str(s.get('employee_code'))[:12]:12} {s.get('status')}: "
              f"{s.get('reason', '')[:60]}")
    print(f"\nTotals: processed={t['rows_processed']} matched={t['matched']} "
          f"violations={t['violations']} sent={t['emails_sent']} "
          f"missing_email={t['emails_missing']} skipped={t['skipped']}")

    # --- 5. reports ---------------------------------------------------------------
    run_id = analysis["run_id"]
    pdf = c.get(f"/api/v1/runs/{run_id}/reports/summary.pdf", headers=m)
    xls = c.get(f"/api/v1/runs/{run_id}/reports/3tab.xlsx", headers=m)
    print(f"\n[5] summary PDF            -> {pdf.status_code} "
          f"({len(pdf.content)} bytes, magic={pdf.content[:4]})")
    print(f"    3-tab Excel            -> {xls.status_code} "
          f"({len(xls.content)} bytes)")
    wb = load_workbook(io.BytesIO(xls.content))
    for name in wb.sheetnames:
        ws = wb[name]
        print(f"      tab '{name}': {ws.max_row - 1} data rows")

    print("\nDONE — dry-run mode: emails recorded as SENT without transmission.")


if __name__ == "__main__":
    main()
