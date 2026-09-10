# Deployment readiness checklist

State of the world: the app is built and hardened for a real deployment, but
has only ever run on localhost + docker-compose. This is everything between
here and production. Nothing here is aspirational — each item is a checkbox.

## 1. Environment variables (production)

Set every one of these; the app already refuses to boot in production with
defaults-insecure settings (JWT key, CORS):

| Var | What | Notes |
|---|---|---|
| `ENVIRONMENT` | `production` | enables strict validators, disables /docs |
| `DATABASE_URL` | managed pg URL with SSL | e.g. RDS/Cloud SQL/Crunchy |
| `JWT_SECRET_KEY` | ≥32 random chars | `openssl rand -hex 32` |
| `CORS_ORIGINS` | exact frontend origin(s) | no wildcard, no localhost |
| `REDIS` (`CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`) | managed Redis | ElastiCache/Upstash; `CELERY_TASK_ALWAYS_EAGER` must NOT be set |
| `STORAGE_BACKEND` + `S3_*` | S3-compatible bucket | do not ship local-disk storage to prod |
| `M365_CLIENT_ID` / `M365_CLIENT_SECRET` / `M365_TENANT_ID` / `M365_REDIRECT_URI` | Entra ID SSO | redirect URI must be https + registered in Azure |
| `GRAPH_*` + `OUTBOUND_EMAIL_MODE=live` | real violation emails | else emails stay `dry_run` |
| `LLM_API_KEY` | optional OCR second-opinion | skip if unused |
| `RETENTION_DAYS` | retention window | default 365 |
| `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` | first MA | change password after first login |

## 2. Secrets management
- **Now (local):** `.env` file — fine for dev, never commit.
- **Production:** platform secret store (Docker secrets, ECS/Fly/GCP/Azure
  secret managers, or Kubernetes Secrets). Inject as env — do not bake into
  images or bake into compose files. Rotate: JWT key rotation invalidates all
  sessions (acceptable, announce downtime); DB/Graph secrets rotate normally.

## 3. Runtime topology
Minimum real deployment = 3 processes + 2 managed services:
- **api** (uvicorn/gunicorn, ≥2 replicas behind a load balancer)
- **worker** (celery -A app.worker …; the OCR queue — the slow path)
- **ocr worker** (`Dockerfile.ocr` image, `paddle` engine) — or keep `rapid`
  on the main worker until volume demands a split
- Managed PostgreSQL (with automated backups — see README "Backups")
- Managed Redis

Fast shutdown order doesn't matter (jobs are idempotent), boot order does:
db → redis → api/worker.

## 4. Docker: dev vs prod
- Current `Dockerfile`/`Dockerfile.ocr` + `docker-compose.yml` are **dev/single-host**
  grade (mounted volumes, no TLS bind mounts, seed users, ports exposed).
- For prod: keep the Dockerfiles (they're sane), write a **separate
  `docker-compose.prod.yml`** (or better, real orchestration): no source
  volumes, `restart: unless-stopped`, healthchecks pointing at
  `/api/v1/health/ready`, resource limits, no published db/redis ports.
- The compose `db` service should not be used in prod; use managed Postgres.

## 5. TLS / HTTPS
- No TLS termination is built into the app — terminate at a load balancer or
  reverse proxy (ALB/CloudFront/Nginx/Caddy/Traefik). The app already emits
  Secure/SameSite cookies, which require HTTPS in prod.
- Redirect http→https; HSTS at the proxy.

## 6. Observability (before launch, not after)
- `/health/ready` (DB+Redis probes) wired to LB health checks.
- `/health` for liveness.
- Logs: structlog JSON → ship stdout to your log platform; every line carries
  `request_id` (frontend sends `X-Request-ID`, every error response echoes it).
- Alert on: 5xx rate, queue depth, worker heartbeats, disk on storage.

## 7. Data lifecycle
- Confirm backup automation + restore drill (README → Backups).
- Set `RETENTION_DAYS`; train MA on the purge button.
- PII inventory: employee names/emails live in `employees` + `employee_versions`
  (soft-delete/versioned — deletion = set `is_deleted`, purge separately if a
  customer demands hard deletion: direct SQL today, an admin endpoint later).

## 8. Security audit status

**Independent Strix deep-scan COMPLETED** (run `veritrack-ai_a203`, NIM
kimi-k3, white-box on full repo). Artifacts: `strix_runs/veritrack-ai_a203/`
(report, SARIF, PoCs). Results: 2 CRITICAL (bootstrap password defaults in
`config.py`/`cli.py` + auto-seed via docker-compose), 1 HIGH (CSV/Excel
formula injection — fix already applied by the scanner to
`app/services/exporters.py` + `reporting.py`; verified, tests green), 1 MEDIUM
(login lockout DoS + 423 enumeration oracle). The two CRITICALs are unfixed —
see the report's remediation before deploying.

Baseline that must still regress-check: `scripts/security_probe.py` 23/23,
bandit 0 medium/high, full pytest suite green.

## 9. Pre-launch smoke checklist
1. All env vars from §1 set; app boots with `ENVIRONMENT=production`.
2. `alembic upgrade head` clean on the production DB.
3. Login as MA (bootstrap CLI), create a Manager, run one real GETS upload
   end-to-end; verify email + reports.
4. `/health/ready` → 200; kill Redis → 503; restore.
5. Browser: no console errors; login, drill-down, analytics render with real
   certs and real domains.
6. Confirm rate limits engage (login, uploads) — they're per-user now, so this
   needs two distinct accounts to test properly.
