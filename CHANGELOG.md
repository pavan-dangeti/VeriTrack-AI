# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). How each change was built, phase by phase, is in
[docs/development-history.md](docs/development-history.md). Every number below comes from a command in this
repository, shown next to it in the [README](README.md#quality-and-test-results).

## [Unreleased]

### Security

- `create-master-admin` and `create-organization` no longer generate a password and print it. The password
  comes from `ADMIN_PASSWORD` or `ORG_ADMIN_PASSWORD`, or a hidden prompt asked twice, and is never printed,
  logged or passed as an argument; `create-master-admin --password` is removed.

### Fixed

- Code scanning findings in the tests (side effects inside asserts, requests to a route that does not exist)
  and in the app (a lambda, a redundant comparison, an implicit string concatenation).

## [3.0.0] - 2026-10-22

### Upgrading from 2.0.0

- Run the migrations (`alembic upgrade head`); 0007–0010 are new. Existing rows move into one
  "Default organisation".
- Migration 0008 creates `veritrack_app`, a role that cannot bypass row-level security. The database login
  role needs `CREATEROLE` to create it; a managed database's owner role has it.
- New optional settings, all with defaults: `JOB_LEASE_SECONDS`, `JOB_MAX_ATTEMPTS`, `JOB_DB_POOL_SIZE`,
  `JOB_DB_POOL_TIMEOUT`, `METRICS_TOKEN`, `DEMO_EMAIL`, `DEMO_PASSWORD`, `DEMO_RESET_HOURS`.

### Added

- **Organisations.** Every tenant table carries an organisation, enforced by PostgreSQL row-level security
  under a role that can never bypass it, as a second layer behind the application's own filters.
  Organisations are created with `python -m app.cli create-organization`.
- **Tamper-evident audit log.** A database trigger chains every entry to the one before it with SHA-256, the
  application may only append, and `python -m app.cli verify-audit-log` and `GET /api/v1/audit-logs/verify`
  report the first entry that no longer fits.
- **Exactly-once background jobs.** Batches and files are claimed with leases that are renewed while the work
  runs; every result write is fenced on the lease token, and a reaper hands lapsed work to another worker.
  A file interrupted `JOB_MAX_ATTEMPTS` times in a row is failed rather than retried forever.
- **Prometheus metrics** at `GET /metrics`, behind `METRICS_TOKEN`: files by outcome, claims and takeovers,
  processing time, queue depth, oldest waiting file and lapsed leases.
- **OCR benchmark**: a synthetic sheet generator, a development set and a held-out set whose seeds were fixed
  before any sheet was generated, and a manual x86-64 workflow (`gh workflow run ocr-benchmark.yml`).
- **Load test**: 200 concurrent users in two scenarios (sign-ins all at once, and spread over 60 s), latency
  in an opening and a steady-state window, and an exactly-once check read from `/metrics`
  (`gh workflow run load-test.yml`).
- **Security scanning in CI**: gitleaks over the tree and every pull request's commits, pip-audit, npm audit
  and Trivy over the API image, and CodeQL, which runs now that the repository is public.
- A read-only public demo account with synthetic data, reset every `DEMO_RESET_HOURS`.
- Design document ([docs/design.md](docs/design.md)), threat model ([docs/threat-model.md](docs/threat-model.md))
  and development history.

### Changed

- The reader handles a generic timesheet layout, and the README describes its columns, hour types and
  statuses.
- Background jobs use a connection pool of their own (`JOB_DB_POOL_SIZE`), separate from requests.
- bcrypt runs on a pool of its own, one thread per CPU, still at cost 12.
- The frontend polls an in-flight batch less often as it ages (every 1.5 s, slowing to every 10 s).
- Credentials were removed from the code and configuration.

### Fixed

- A sign-in that failed silently while the free-plan API was still waking up.
- Generated reports were stored next to uploaded files.
- Purging old batches removed their rows but left their stored files.
- Sign-in held a database connection through bcrypt; uploads, reports, exports and downloads held one through
  storage and build work. Under load this ran the pool dry (HTTP 500).
- bcrypt shared the default thread pool with storage I/O.
- Fixed-interval polling starved OCR under load.
- An upload burst starved requests while jobs shared the request pool.
- A job that waited too long for a connection was recorded as a failed file; jobs now wait up to
  `JOB_DB_POOL_TIMEOUT`.
- A race in the end-to-end suite: the grid's filter was closed before it had been applied.

### Security

- The first audit verifier trusted a database function that could be redefined; the verifier now rebuilds each
  entry's canonical text in Python from its raw fields.
- Vite, Vitest and undici upgraded past known vulnerabilities found by npm audit.

### Measured

- OCR, 220 held-out sheets on x86-64: 96 read exactly (43.6 %), and 1 sheet passed verification with a wrong
  value (`gh workflow run ocr-benchmark.yml -f seed=4729`).
- 200 concurrent users on a 2 vCPU x86-64 runner: steady-state p50 29 ms (sign-ins at once) and 26 ms (spread
  over 60 s); 160/160 results correct, 0 errors, 480/480 files processed exactly once in both runs
  (`gh workflow run load-test.yml -f ramp_seconds=0` and `-f ramp_seconds=60`).
- Tests: 379 backend (`pytest tests`), 59 frontend (`npm test`), 48 end-to-end against the production build
  (`pytest e2e`).

## [2.0.0] - 2026-09-25

The initial version.

### Added

- FastAPI service and React app with four roles: Master Admin, Executive, Manager and HR.
- Timesheet screenshot reading with verification against the sheet's own totals; anything unproven is sent to
  review.
- Employee repository and leave register imports (CSV or Excel), leave checks, violation e-mails, and PDF and
  Excel reports.
- Render blueprints and Vercel configuration.

[Unreleased]: https://github.com/pavan-dangeti/VeriTrack-AI/compare/v3.0.0...HEAD
[3.0.0]: https://github.com/pavan-dangeti/VeriTrack-AI/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/pavan-dangeti/VeriTrack-AI/releases/tag/v2.0.0
