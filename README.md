# VeriTrack AI — Backend Foundation

Enterprise employee leave-compliance & document-intelligence platform.
This repo currently contains the **security foundation**: DB-enforced role
hierarchy, dual authentication (Microsoft Entra ID SSO + email/password),
JWT sessions with refresh-token rotation, RBAC on every route, rate limiting,
CSRF protection, and a durable audit trail.

## Stack

- FastAPI (Python 3.14) + SQLAlchemy 2 async + Alembic
- PostgreSQL (native enums, partial unique index, hierarchy triggers)
- bcrypt (cost 12+), PyJWT (HS256; swap to RS256 when multiple services verify)
- structlog JSON logging, slowapi rate limiting

## Layout

```
app/
  core/        config (env-only secrets), security utils, permissions map, rate limits, logging
  db/          engine/session, declarative base
  models/      users, audit_logs, approved_m365_domains, refresh_tokens
  schemas/     Pydantic request/response models
  services/    auth, users, audit, m365 (business logic lives here)
  api/
    deps.py    get_current_user, require_role(...), CSRF, request context
    routers/   auth, users, audit-logs, health
alembic/       migrations (0001_foundation creates all constraints/triggers)
tests/         pytest suite against real PostgreSQL
```

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # dev defaults work against local PG

# Postgres: either `docker compose up -d db`
# or create role/db manually:
psql -d postgres -c "CREATE ROLE veritrack LOGIN PASSWORD 'veritrack' CREATEDB"
psql -d postgres -c "CREATE DATABASE veritrack OWNER veritrack"

alembic upgrade head
python -m app.cli create-master-admin          # uses SEED_ADMIN_* from .env; without
                                               # --password it generates one and prints it once
uvicorn app.main:app --reload                  # http://localhost:8000/docs
```

### Migrations

```bash
alembic upgrade head        # apply
alembic downgrade -1        # roll back one step
alembic revision -m "..."   # new empty migration
```

### Tests

Requires the test DB (auto-created if the role exists):

```bash
psql -d postgres -c "CREATE DATABASE veritrack_test OWNER veritrack"  # once
.venv/bin/python -m pytest -q
```

Tests run **real Alembic migrations** against `veritrack_test` and truncate all
tables between tests. The rate limiter is reset per test.

## Bootstrap CLI

```bash
python -m app.cli create-master-admin --password 'Your!Strong1Pass'  # or SEED_ADMIN_PASSWORD env
# no password given => a strong random one is generated and printed exactly once
python -m app.cli approve-domain contoso.com     # allowlist for SSO logins
```

There is no default bootstrap password anywhere. docker-compose fails fast at
startup if `SEED_ADMIN_PASSWORD` is unset, so a fresh deployment can never
ship a publicly known Master Admin credential.

The Master Admin is the only seeded account. Everything else is created via the
API (`POST /api/v1/users`) by an authorized role; the response carries a
server-generated initial password shown exactly once.

## Security model (enforced where?)

| Rule | Enforced by |
|---|---|
| Max one Master Admin | partial unique index `uq_users_single_master_admin` |
| HR must hang off a MANAGER; created by a MANAGER | trigger `trg_user_role_hierarchy` |
| MANAGER/EXECUTIVE created by MASTER_ADMIN only | same trigger |
| Password users always have a hash | CHECK `chk_users_password_auth` |
| Role checks per endpoint | `require_role(...)` dependency; denials audited as DENIED |
| Manager sees only own HRs | query-layer scoping in `user_service.list_users_scoped` |
| Brute force | lockout: 5 failures → locked `LOCKOUT_DURATION_MINUTES`; 10 req/min/IP on login |
| Token theft | refresh rotation + family revocation on replay |
| CSRF | double-submit token on cookie-based endpoints (refresh/logout) |
| Secrets | env only; production refuses default JWT key / wildcard CORS |

## Auth flow summary

- `POST /api/v1/auth/login` → access token (15 min, Authorization header) +
  refresh cookie (7 days, HttpOnly/Secure/SameSite=Strict)
- `GET  /api/v1/auth/m365/login` → Entra ID redirect (PKCE); callback validates
  JWKS signature, issuer, audience, nonce, then requires the email domain in
  `approved_m365_domains` and an existing active account
- `POST /api/v1/auth/refresh` → rotates refresh token; replaying an old one
  revokes every session for that user
- Every login attempt (success/failure/denied) is written to `audit_logs`

## Docker

```bash
docker compose up --build   # db + api (runs migrations + seeds MA automatically)
```

## What's next (per project plan)

Employee repository ingestion, GETS monthly processing pipeline, compliance
analysis engine, and reporting fan-out build on this foundation.

## OCR / scanned documents

| Engine | Where it runs | Notes |
|---|---|---|
| `OCR_ENGINE=rapid` (default via `auto`) | anywhere incl. py3.14/macOS | RapidOCR = PaddleOCR models in ONNX, CPU-only |
| `OCR_ENGINE=paddle` | linux workers only (`Dockerfile.ocr`, python:3.12) | full PaddleOCR + Table Transformer sidecar; shares Redis/Postgres, runs as a Celery worker on the `ocr` queue |
| `PENDING_OCR` fallback | n/a | if no engine is installed, scanned/image files are stored and marked `PENDING_OCR` (not failed); retry via `POST /api/v1/uploads/batches/{id}/files/{fid}/reprocess` after installing an engine |

Scanned PDFs are rasterized with pypdfium2 before recognition. Table
reconstruction handles word-level OCR boxes, multi-word/fuzzy headers
(`EmployeeID`, `FulName`), and merged-line detections (regex-based field
extraction fallback). Low-confidence rows are flagged for review or corrected
by the LLM verifier when an API key is configured.

## Backups & disaster recovery

The single source of truth is PostgreSQL (`veritrack`); uploaded files live in
object storage (`storage_backend`: local dir or S3), which must be backed up
alongside the DB.

**Backup schedule (recommended baseline)**
- DB: `pg_dump --format=custom veritrack` nightly, keep 30 daily + 12 monthly
  snapshots. On a managed provider (RDS/Cloud SQL/Crunchy/Neon) enable
  automated backups + point-in-time recovery (PITR) and rely on that instead.
- Objects: S3 versioning + lifecycle, or nightly `rsync`/`s3 sync` of
  `LOCAL_STORAGE_ROOT` to a second location.
- Retention: see `RETENTION_DAYS`; the System Settings → "Purge obsolete data"
  action removes old batches/reports. Employee records are never hard-deleted.

**Recovery procedure**
1. Provision a fresh PostgreSQL and restore: `pg_restore --clean --create -d postgres veritrack-<date>.dump`
   (managed providers: "restore to new instance").
2. Restore `LOCAL_STORAGE_ROOT` from the file/object backup.
3. Point the app at the restored DB (`DATABASE_URL`), run `alembic upgrade head`
   (no-op if the dump is current), then redeploy.
4. Smoke-check: `/health/ready` must return 200 (DB + Redis), then log in as
   Master Admin and open one manager's dashboard.
5. Decide about in-flight Celery jobs: any batch marked PROCESSING/QUEUED at
   backup time should be re-triggered — files are still in storage, nothing is
   lost; simply reprocess the batch.

RPO/RTO targets to agree before launch: RPO ≤ 24h (nightly dump) or minutes
(PITR); RTO ~1h including verification. Run a restore drill before go-live —
an untested backup is not a backup.
