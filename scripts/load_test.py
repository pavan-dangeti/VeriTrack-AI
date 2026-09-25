"""Concurrent-user load test against a running API.

    python -m scripts.load_test --base http://localhost:8000 --managers 40 --hr 10

Every simulated user comes from its own client address (X-Forwarded-For, one
trusted proxy hop), logs in at the same moment, and managers each upload an
employee repository, a leave register and a GETS screenshot, wait for OCR,
run the analysis and check the result. HR users keep browsing the whole time
so the report shows how responsive the API stays while OCR is busy. Results
are checked per user: the right violations, and no other manager's data.

Needs a Master Admin (ADMIN_EMAIL / ADMIN_PASSWORD env vars).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ROOT / "test-data" / "synthetic"
SHEETS = {  # synthetic sheet -> employee expected to be flagged (None = compliant)
    "synthetic_000.png": None,
    "synthetic_004.png": None,
    "synthetic_007.png": ("141220", "2025-07-28"),
    "synthetic_013.png": ("197061", "2025-06-18"),
}
REPO_CSV = (
    "Employee ID,Full Name,Company Email\n"
    "103729,Golf Anonymous,golf@example.com\n158082,Kilo Specimen,kilo@example.com\n"
    "141220,Bravo Example,bravo@example.com\n197061,Echo Specimen,echo@example.com\n"
)
LEAVE_CSV = (
    "Employee ID,From Date,To Date\n103729,09-03-2026,\n103729,2026-03-24,\n"
    "141220,01/07/2025,\n141220,03-Jul-2025,\n141220,2025-07-14,\n"
    "197061,02-Jun-2025,03-Jun-2025\n197061,11/06/2025,\n"
)


class Stats:
    def __init__(self) -> None:
        self.latency: dict[str, list[float]] = {}
        self.errors: list[str] = []

    def add(self, name: str, seconds: float) -> None:
        self.latency.setdefault(name, []).append(seconds * 1000)

    def summary(self) -> dict:
        out = {}
        for name, xs in sorted(self.latency.items()):
            xs = sorted(xs)
            out[name] = {
                "count": len(xs),
                "p50_ms": round(statistics.median(xs), 1),
                "p95_ms": round(xs[int(0.95 * (len(xs) - 1))], 1),
                "max_ms": round(xs[-1], 1),
            }
        return out


class User:
    def __init__(self, base: str, ip: str, stats: Stats) -> None:
        self.http = httpx.AsyncClient(base_url=base, timeout=300, headers={"X-Forwarded-For": ip})
        self.stats = stats

    async def call(self, name: str, method: str, url: str, expect: int | tuple = 200, **kw) -> httpx.Response:
        t = time.perf_counter()
        r = await self.http.request(method, url, **kw)
        self.stats.add(name, time.perf_counter() - t)
        ok = r.status_code in (expect if isinstance(expect, tuple) else (expect,))
        if not ok:
            self.stats.errors.append(f"{name}: {r.status_code} {r.text[:160]}")
        return r

    async def login(self, email: str, password: str) -> None:
        r = await self.call("login", "POST", "/api/v1/auth/login", json={"email": email, "password": password})
        self.http.headers["Authorization"] = f"Bearer {r.json()['access_token']}"


async def create_accounts(base: str, stats: Stats, managers: int, hr: int, tag: str):
    root = User(base, "192.0.2.1", stats)
    await root.login(os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"])
    accounts = []
    for i in range(managers):
        email = f"load.m{i}.{tag}@veritrack.io"
        r = await root.call("create_user", "POST", "/api/v1/users", 201, json={"email": email, "role": "MANAGER"})
        accounts.append(("MANAGER", email, r.json()["initial_password"], i))
    for i in range(hr):
        owner = accounts[i % managers]
        mgr = User(base, f"192.0.2.{10 + i}", stats)
        await mgr.login(owner[1], owner[2])
        email = f"load.h{i}.{tag}@veritrack.io"
        r = await mgr.call("create_user", "POST", "/api/v1/users", 201, json={"email": email, "role": "HR"})
        accounts.append(("HR", email, r.json()["initial_password"], i))
        await mgr.http.aclose()
    await root.http.aclose()
    return accounts


async def manager_flow(base: str, stats: Stats, email: str, password: str, i: int, results: dict) -> None:
    u = User(base, f"198.51.{i // 250}.{i % 250 + 1}", stats)
    await u.login(email, password)
    await u.call("upload_repo", "POST", "/api/v1/uploads?kind=EMPLOYEE_REPO", 201,
                 files=[("files", ("repo.csv", REPO_CSV.encode(), "text/csv"))])
    await u.call("upload_leaves", "POST", "/api/v1/uploads?kind=COMPANY_LEAVE", 201,
                 files=[("files", ("leave.csv", LEAVE_CSV.encode(), "text/csv"))])
    sheet = list(SHEETS)[i % len(SHEETS)]
    data = (SYNTHETIC / sheet).read_bytes()
    t0 = time.perf_counter()
    batch = (await u.call("upload_gets", "POST", "/api/v1/uploads?kind=GETS", 201,
                          files=[("files", (sheet, data, "image/png"))])).json()
    while True:
        detail = (await u.call("poll_batch", "GET", f"/api/v1/uploads/batches/{batch['id']}")).json()
        if detail["status"] in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(2)
    ocr_wait = time.perf_counter() - t0
    await u.call("analyze", "POST", f"/api/v1/batches/{batch['id']}/analyze", 202)
    while True:
        res = await u.call("poll_analysis", "GET", f"/api/v1/batches/{batch['id']}/analysis", (200, 404))
        if res.status_code == 200 and res.json()["status"] != "RUNNING":
            break
        await asyncio.sleep(1)
    analysis = res.json()
    flagged = sorted((v["employee_code"], (v.get("details") or {}).get("missing_in_register", [None])[0])
                     for v in analysis["violations"])
    expected = [SHEETS[sheet]] if SHEETS[sheet] else []
    own = {b["id"] for b in (await u.call("list_batches", "GET", "/api/v1/uploads/batches")).json()}
    results[email] = {
        "sheet": sheet,
        "sheet_status": detail["files"][0].get("sheet_status"),
        "ocr_wait_s": round(ocr_wait, 1),
        "correct": flagged == expected and detail["files"][0]["status"] == "DONE",
        "isolated": len(own) == 3,
        "flagged": flagged,
    }
    await u.http.aclose()


async def hr_browse(base: str, stats: Stats, email: str, password: str, i: int, stop: asyncio.Event) -> None:
    u = User(base, f"203.0.113.{i + 1}", stats)
    await u.login(email, password)
    while not stop.is_set():
        await u.call("browse_dashboard", "GET", "/api/v1/dashboard/summary")
        await u.call("browse_batches", "GET", "/api/v1/uploads/batches")
        await u.call("browse_employees", "GET", "/api/v1/employees")
        await u.call("browse_leaves", "GET", "/api/v1/leaves")
        await asyncio.sleep(0.5)
    await u.http.aclose()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--managers", type=int, default=40)
    ap.add_argument("--hr", type=int, default=10)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from scripts.gen_synthetic_gets import ensure

    if ensure(SYNTHETIC) is None:
        raise SystemExit("could not generate the synthetic GETS sheets (needs Playwright + Chromium)")
    stats = Stats()
    tag = str(int(time.time()))
    accounts = await create_accounts(args.base, stats, args.managers, args.hr, tag)
    stats.latency.pop("login", None)

    results: dict = {}
    stop = asyncio.Event()
    started = time.perf_counter()
    browsers = [asyncio.create_task(hr_browse(args.base, stats, e, p, i, stop))
                for role, e, p, i in accounts if role == "HR"]
    await asyncio.gather(*(manager_flow(args.base, stats, e, p, i, results)
                           for role, e, p, i in accounts if role == "MANAGER"))
    stop.set()
    await asyncio.gather(*browsers)
    wall = time.perf_counter() - started

    report = {
        "users": {"managers": args.managers, "hr": args.hr},
        "wall_clock_s": round(wall, 1),
        "sheets_processed": len(results),
        "all_results_correct": all(r["correct"] for r in results.values()),
        "all_users_isolated": all(r["isolated"] for r in results.values()),
        "ocr_wait_s": {
            "p50": statistics.median(r["ocr_wait_s"] for r in results.values()),
            "max": max(r["ocr_wait_s"] for r in results.values()),
        },
        "errors": stats.errors[:20],
        "error_count": len(stats.errors),
        "latency": stats.summary(),
        "wrong": {e: r for e, r in results.items() if not (r["correct"] and r["isolated"])},
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text)
    return 0 if report["all_results_correct"] and report["all_users_isolated"] and not stats.errors else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
