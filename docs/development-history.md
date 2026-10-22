# Development history

VeriTrack is a personal project. This page records how it was built: the starting point, then each phase
and the pull requests that made it up. The pull requests were opened in an earlier private repository;
their numbers are kept here so the history reads in order, but the links no longer exist. Dates are when a
pull request was opened and when it was merged.

## Starting point (25–28 September 2026)

- **25 Sep:** the initial version: the FastAPI service, the React app, timesheet and leave-register
  imports, leave checks, reports and e-mails. Tagged `v2.0.0` with the Render blueprint added the same day.
- **28 Sep:** fixed a sign-in that failed silently while the free-plan API was still waking up.

## Phase 1: a reader I could measure

- **#1 Generic timesheet, credential hygiene and a public demo account** (8 Oct → 8 Oct). Moved the reader
  to a generic timesheet layout, cleaned credentials out of the code and config, and added a read-only demo
  account for the live site.
- **#2 Docs: the sheet's columns, hour types and statuses** (8 Oct → 8 Oct). Brought the OCR section of the
  README in line with the sheet the reader now handles.
- **#3 Store reports apart from uploads again** (8 Oct → 8 Oct). Fixed a storage prefix left behind by #1 that
  put generated reports next to uploaded files.
- **#4 OCR benchmark workflow on x86-64** (13 Oct → 13 Oct). A manual CI workflow that runs the OCR benchmark
  on the same processor type as production, so published numbers don't depend on my laptop.
- **#5 OCR accuracy at realistic scale** (13 Oct → 14 Oct). A synthetic sheet generator, a development set and
  a held-out set whose seeds were fixed before any sheet was generated, and the fixes the development set
  showed were needed. The held-out set was read once, at a frozen commit: 96 of 220 sheets exact, and 1 sheet
  passed verification with a wrong value.

## Phase 2: organisations

- **#6 Multi-tenancy with organisations and row-level security** (14 Oct → 14 Oct). Merged by mistake into the
  Phase 1 branch instead of main, so it was opened again as #7.
- **#7 The same change, onto main** (15 Oct → 15 Oct). Every tenant table got an organisation, PostgreSQL
  row-level security enforced under a role that cannot bypass it, and tests that try to cross organisations
  on every route.
- **#8 Retention purge deletes stored files too** (15 Oct → 20 Oct). Purging old batches removed their rows but
  left their files in storage; now both go.

## Phase 3: an audit log that can't be quietly edited

- **#9 Hash-chained audit log** (15 Oct → 20 Oct). A database trigger chains every audit entry to the one
  before it, the app may only append, and a verifier (CLI and API) finds the first entry that was changed.
  A review found the first verifier trusted a database function that could be redefined; it now rebuilds
  each entry in Python.
- **#10 Threat model: purges delete files as well as rows** (20 Oct → 20 Oct). Updated the threat model for #8.

## Phase 4: reliability under load

- **#11 Load-test workflow on x86-64** (20 Oct → 20 Oct). A manual CI workflow that runs the load test against
  a fresh deployment.
- **#12 Exactly-once OCR jobs, queue metrics and a 200-user load test** (20 Oct → 22 Oct). Jobs claim work with
  leases and write results only while they hold them, and a reaper hands lapsed work to another worker.
  Tests kill and freeze a real worker mid-file. Added Prometheus metrics. The load test found four bugs,
  fixed here: sign-in held a database connection through bcrypt; uploads, reports, exports and downloads
  held one through storage and build work; bcrypt starved the shared thread pool; and fixed-interval polling
  starved OCR (polling now backs off as a batch ages).

## Phase 5: security and documentation

- **#13 Security scanning, design doc and load-test windows** (22 Oct → 22 Oct). gitleaks, pip-audit, npm audit
  and Trivy in CI (CodeQL once the repository is public), a design document, and load-test results split into
  opening and steady-state windows, with a ramped scenario alongside the burst. Load-test reruns found two
  more bugs, fixed here: background jobs shared the request connection pool, so an upload burst starved
  requests (jobs now have their own pool), and a job that waited too long for a connection was recorded as a
  failed file (it now waits). npm audit found vulnerable dev tools; Vite, Vitest and undici were upgraded.
- **#14 Cleanup** (22 Oct → 22 Oct). Checked for dead code (none found), fixed an end-to-end test that raced
  the grid's filter, called VeriTrack a personal project on the sign-in page, corrected two README claims,
  and regenerated the screenshots and demo video.
