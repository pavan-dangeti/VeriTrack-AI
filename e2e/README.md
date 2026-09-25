# VeriTrack AI — real-browser end-to-end suite

Playwright (sync API, Chromium) + pytest. It drives the running app exactly as
a user would — every sidebar page for every role, every button/form/download,
the full manager workflow (repository → leave register → GETS upload → review
→ analysis → reports), role isolation, the app shell (sidebar, theme, Ctrl+K,
mobile drawer) and negative cases.

It is completely separate from the API test suite in `tests/`:
`e2e/pytest.ini` makes `e2e/` its own pytest rootdir, so `tests/conftest.py`
and the pyproject pytest settings are never loaded (and vice versa).

## Prerequisites

1. PostgreSQL up, migrations applied, Master Admin seeded
   (`python -m app.cli create-master-admin --if-not-exists`).
2. Backend on :8000 — `uvicorn app.main:app --port 8000`
   (`PROCESSING_MODE=background`, RapidOCR installed for real GETS extraction).
3. Frontend on :5173 — `cd frontend && npx vite --port 5173` (proxies `/api`).
4. Playwright's Chromium: `playwright install chromium` (or point `E2E_CHROMIUM` at a Chrome/Chromium binary).

## Run

```bash
export E2E_ADMIN_EMAIL=admin@veritrack.io
export E2E_ADMIN_PASSWORD='…'          # the seeded Master Admin password
.venv/bin/python -m pytest e2e -q
```

| Variable | Default | Meaning |
|---|---|---|
| `E2E_BASE_URL` | `http://localhost:5173` | Frontend URL (API reached through its `/api` proxy) |
| `E2E_ADMIN_EMAIL` / `E2E_ADMIN_PASSWORD` | `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` from the repo `.env` | Master Admin login |
| `E2E_SHOTS_DIR` | `e2e/.artifacts` (git-ignored) | Screenshots (one per page per role) + every downloaded file |
| `E2E_CHROMIUM` | Playwright's Chromium | Chromium executable |
| `E2E_HEADED` | unset | set to `1` to watch the browser |

If the frontend/API is not reachable, the credentials are missing, or
Chromium is not found, the whole suite is **skipped** with the reason.

Every run creates fresh, uniquely named accounts
(`e2e.<role>.<MMDDhhmmss>@example.com`), so reruns never collide. Only
fictional data is used: synthetic sheets `synthetic_000/004/007/013.png`, generated on first run into the
git-ignored `test-data/synthetic/`, plus the repository/leave CSVs from `tests/test_timesheet_leave_flow.py`.
The suite never touches `private-data/`.

## What is checked on every page

`conftest.py` attaches a *guard* to every browser page. A test **fails** if,
while it ran, any page produced:

* an uncaught JavaScript error;
* a `console.error` (Google-Fonts / proxy noise excluded);
* an `/api` response ≥ 500, or any 4xx that the test did not declare with
  `guard.allow(...)` (the pre-login `POST /auth/refresh` 401 and the
  "no analysis yet" `GET /batches/:id/analysis` 404 are allowed globally);
* a failed `/api` request, or a same-origin asset 4xx;
* an **error toast** the test did not expect (`guard.allow_toast(...)`).

## Layout

| File | Covers |
|---|---|
| `test_01_login.py` | redirect to /login, field validation, wrong password, deep-link return, reload keeps the session, logout |
| `test_02_admin.py` | all Master Admin pages, create Manager + Executive (one-time password dialog, copy), duplicate refused, disable/enable (+ disabled login refused), SSO domain, drill-down, purge (cancel + confirm), audit filters/export/paging/sort, forbidden URLs |
| `test_03_manager.py` | first login, repository upload/filter/sort/detail, leave register upload/filter/add/cancel/delete, GETS upload with live progress, every sheet's review (image vs grid, checks, view tabs), re-extract, export, analysis (double-click safe) with the 2 expected violations, PDF/XLSX downloads, reports, HR account creation, dashboard numbers, analytics, profile, forbidden URLs |
| `test_04_admin_oversight.py` | cross-manager uploads/review/results, read-only repositories, all reports, read-only leaves, analytics by manager |
| `test_05_hr.py` | HR first login, every page, CSV/XLSX downloads, read-only leave register, blocked URLs |
| `test_06_executive.py` | every page, analytics, repositories, reports + results, directory → manager → HR → manager drill-down, blocked URLs |
| `test_07_shell.py` | sidebar collapse persistence, dark/light persistence, Ctrl+K palette (keys + mouse), unknown routes, 390×844 mobile drawer + no horizontal scroll |
| `test_08_negative.py` | .txt / fake .png / empty / 21-file uploads rejected with a toast, garbage repository file, non-GETS image, bad drill-down URLs, rapid navigation |
| `test_09_resend.py` | "Resend" reports, then downloads still work (runs last) |

Modules can be run on their own (`pytest e2e/test_05_hr.py`); accounts and
data that earlier modules would have created through the UI are then set up
through the API instead.
