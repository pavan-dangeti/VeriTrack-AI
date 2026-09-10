<div align="center">

# 🛡️ VeriTrack AI

**Industry-Grade Enterprise Employee Compliance Verification Platform**

[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](./LICENSE)
[![Status](https://img.shields.io/badge/Backend-Production_Ready-success?style=for-the-badge)]()

![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-LangGraph-blueviolet?style=flat-square)
![JWT](https://img.shields.io/badge/JWT-Secured-orange?style=flat-square)
![PaddleOCR](https://img.shields.io/badge/PaddleOCR-Document_AI-red?style=flat-square)

> VeriTrack AI is an industry-grade backend platform that automates employee compliance verification by comparing employee master data with monthly GETS sheets. It delivers secure dual authentication, role-based access control, AI-powered compliance recommendations, OCR-based document processing, automated report generation, audit logging, and real-time analytics — all through a production-ready RESTful API layer.

</div>

---

## 🏗️ System Overview

```
                    ┌─────────────────────────────┐
                    │         React Frontend        │
                    │     (Production — Private)    │
                    └──────────────┬──────────────┘
                                   │ REST API
                    ┌──────────────▼──────────────┐
                    │        FastAPI Backend        │
                    │   ┌─────────────────────┐    │
                    │   │  JWT Auth + RBAC    │    │
                    │   │  (+ Entra ID SSO)   │    │
                    │   ├─────────────────────┤    │
                    │   │  Compliance Engine  │    │
                    │   ├─────────────────────┤    │
                    │   │  AI Recommendation  │    │
                    │   │  (LangChain/Graph)  │    │
                    │   ├─────────────────────┤    │
                    │   │   OCR Processing    │    │
                    │   │  (RapidOCR/Paddle)  │    │
                    │   ├─────────────────────┤    │
                    │   │  Report Generation  │    │
                    │   │  (ReportLab)        │    │
                    │   └─────────────────────┘    │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │     PostgreSQL Database       │
                    └─────────────────────────────┘
```

---

## ✨ Core Modules

### 🔐 Authentication & Authorization
- Dual authentication: Microsoft Entra ID SSO (PKCE) + email/password
- JWT sessions with refresh-token rotation and family revocation on replay
- Role-Based Access Control (RBAC) enforced on every route, with DB-level role hierarchy
- Account lockout after repeated failed attempts (brute-force protection)
- CSRF protection (double-submit token) on cookie-based endpoints
- Per-endpoint rate limiting

### 👥 Employee Management
- Employee master data upload (Excel/CSV)
- Full-text employee search & filter
- Department & manager-wise mapping
- Employee database CRUD management

### ✅ Compliance Verification Engine
- Automated comparison of employee database vs. GETS sheet
- Missing / unknown employee detection
- Missing email detection
- Department-wise compliance summary
- Compliance score calculation (0–100%)
- Risk level classification (Low / Medium / High / Critical)
- **AI-based recommendations** using LangChain + LangGraph

### 📄 OCR & Document Processing
- Dual OCR engine setup: RapidOCR (ONNX, CPU-only, cross-platform) by default, with an optional PaddleOCR + Table Transformer worker for Linux/Docker deployments
- Scanned PDFs rasterized via pypdfium2 before recognition
- Table reconstruction handling word-level OCR boxes, fuzzy/multi-word headers, and merged-line detections
- Graceful `PENDING_OCR` fallback with reprocess endpoint if no engine is installed
- SHA-256 duplicate file detection and secure filename sanitization

### 📊 Report Management
- Automated compliance report generation (PDF via ReportLab)
- Report history & upload history tracking
- Downloadable reports per compliance cycle
- Full audit log trail

### 🔔 Notifications
- Compliance report delivery via email
- Password reset email flow
- Background async task processing (Celery)

### ⚙️ Background Processing
- Asynchronous GETS sheet processing
- Auto-triggered report generation post-analysis
- Celery-based background task queue

---

## 🔒 Security Model

| Rule | Enforced by |
|---|---|
| Max one Master Admin | partial unique index `uq_users_single_master_admin` |
| HR must hang off a MANAGER; created by a MANAGER | trigger `trg_user_role_hierarchy` |
| MANAGER/EXECUTIVE created by MASTER_ADMIN only | same trigger |
| Password users always have a hash | CHECK `chk_users_password_auth` |
| Role checks per endpoint | `require_role(...)` dependency; denials audited as DENIED |
| Manager sees only own HRs | query-layer scoping in `user_service.list_users_scoped` |
| Brute force | lockout after 5 failures; 10 req/min/IP on login |
| Token theft | refresh rotation + family revocation on replay |
| CSRF | double-submit token on cookie-based endpoints (refresh/logout) |
| Secrets | env only; production refuses default JWT key / wildcard CORS |

There is no default bootstrap password anywhere — docker-compose fails fast at startup if `SEED_ADMIN_PASSWORD` is unset, so a fresh deployment can never ship a publicly known Master Admin credential.

### Auth flow summary

- `POST /api/v1/auth/login` → access token (15 min, Authorization header) + refresh cookie (7 days, HttpOnly/Secure/SameSite=Strict)
- `GET  /api/v1/auth/m365/login` → Entra ID redirect (PKCE); callback validates JWKS signature, issuer, audience, nonce, then requires the email domain in `approved_m365_domains` and an existing active account
- `POST /api/v1/auth/refresh` → rotates refresh token; replaying an old one revokes every session for that user
- Every login attempt (success/failure/denied) is written to `audit_logs`

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI (Python 3.14) |
| ORM | SQLAlchemy 2 (async) + Alembic |
| Database | PostgreSQL (native enums, partial unique index, hierarchy triggers) |
| Authentication | JWT (PyJWT, HS256) · bcrypt (cost 12+) · Microsoft Entra ID SSO |
| Data Processing | Pandas · OpenPyXL |
| OCR | RapidOCR (default) · PaddleOCR + Table Transformer (Linux/Docker) · PyMuPDF · pdfplumber · pypdfium2 |
| AI Engine | LangChain · LangGraph |
| Reporting | ReportLab |
| Logging & Rate Limiting | structlog (JSON) · slowapi |
| Background Jobs | Celery |
| Containerization | Docker · Docker Compose |
| API Docs | Swagger UI (auto-generated) |

---

## 📡 API Reference

| Module | Endpoints |
|---|---|
| Authentication | Login, Logout, Refresh, SSO, Password Reset |
| User Management | Create, Update, Delete, Role Assignment |
| Employee Management | Upload, Search, Filter, CRUD |
| Upload Management | GETS Sheet Upload, History, Reprocess |
| Compliance Engine | Run Analysis, Department Summary, Score |
| AI Recommendations | Generate, Retrieve |
| Dashboard | Metrics, Charts, Analytics |
| Manager Dashboard | Team Compliance View |
| HR Dashboard | Organization-wide View |
| Reports | Generate, Download, History |
| Audit Logs | Full Activity Trail |
| Health Check | `/health/ready` (DB + Redis) |

Full interactive API documentation available at: `http://localhost:8000/docs`

---

## 📁 Project Structure

```
app/
  core/          config (env-only secrets), security utils, permissions map, rate limits, logging
  db/            engine/session, declarative base
  models/        users, audit_logs, approved_m365_domains, refresh_tokens
  schemas/       Pydantic request/response models
  services/      auth, users, audit, m365, compliance, ocr, reports (business logic)
  api/
    deps.py      get_current_user, require_role(...), CSRF, request context
    routers/     auth, users, audit-logs, analytics, dashboard, health
alembic/         migrations
frontend/        React + TypeScript production dashboard
scripts/         maintenance & diagnostic scripts
tests/           pytest suite against real PostgreSQL
```

---

## 🚀 Getting Started

### Prerequisites
- Python 3.14
- PostgreSQL 14+
- Docker & Docker Compose (optional)

### Local Setup

```bash
git clone https://github.com/pavan-dangeti/VeriTrack-AI.git
cd VeriTrack-AI

python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # dev defaults work against local PG

# Postgres: either `docker compose up -d db`
# or create role/db manually:
psql -d postgres -c "CREATE ROLE veritrack LOGIN PASSWORD 'veritrack' CREATEDB"
psql -d postgres -c "CREATE DATABASE veritrack OWNER veritrack"

alembic upgrade head
python -m app.cli create-master-admin          # uses SEED_ADMIN_* from .env; without
                                                 # --password it generates one and prints it once
uvicorn app.main:app --reload                   # http://localhost:8000/docs
```

### Bootstrap CLI

```bash
python -m app.cli create-master-admin --password 'Your!Strong1Pass'  # or SEED_ADMIN_PASSWORD env
python -m app.cli approve-domain contoso.com     # allowlist for SSO logins
```

The Master Admin is the only seeded account. Everything else is created via the API (`POST /api/v1/users`) by an authorized role; the response carries a server-generated initial password shown exactly once.

### Migrations

```bash
alembic upgrade head        # apply
alembic downgrade -1        # roll back one step
alembic revision -m "..."   # new empty migration
```

### Tests

```bash
psql -d postgres -c "CREATE DATABASE veritrack_test OWNER veritrack"  # once
.venv/bin/python -m pytest -q
```

Tests run real Alembic migrations against `veritrack_test` and truncate all tables between tests. The rate limiter is reset per test.

### Environment Variables

```env
DATABASE_URL=postgresql://user:password@localhost/veritrack
SECRET_KEY=your_secret_key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=your_email@gmail.com
SMTP_PASSWORD=your_app_password

SEED_ADMIN_PASSWORD=set_this_in_production
```

### Docker Deployment

```bash
docker compose up --build   # db + api (runs migrations + seeds Master Admin automatically)
```

API available at: `http://localhost:8000`
Swagger docs at: `http://localhost:8000/docs`

---

## 🖨️ OCR Engine Setup

| Engine | Where it runs | Notes |
|---|---|---|
| `OCR_ENGINE=rapid` (default via `auto`) | anywhere incl. Python 3.14/macOS | RapidOCR = PaddleOCR models in ONNX, CPU-only |
| `OCR_ENGINE=paddle` | Linux workers only (`Dockerfile.ocr`, python:3.12) | full PaddleOCR + Table Transformer sidecar; shares Redis/Postgres, runs as a Celery worker on the `ocr` queue |
| `PENDING_OCR` fallback | n/a | if no engine is installed, scanned/image files are stored and marked `PENDING_OCR` (not failed); retry via `POST /api/v1/uploads/batches/{id}/files/{fid}/reprocess` after installing an engine |

Low-confidence rows are flagged for review or corrected by the LLM verifier when an API key is configured.

---

## 💾 Backups & Disaster Recovery

The single source of truth is PostgreSQL (`veritrack`); uploaded files live in object storage (local dir or S3), which must be backed up alongside the DB.

**Backup schedule (recommended baseline)**
- DB: `pg_dump --format=custom veritrack` nightly, keep 30 daily + 12 monthly snapshots. On a managed provider (RDS/Cloud SQL/Crunchy/Neon) enable automated backups + point-in-time recovery (PITR) instead.
- Objects: S3 versioning + lifecycle, or nightly `rsync`/`s3 sync` of `LOCAL_STORAGE_ROOT` to a second location.
- Retention: see `RETENTION_DAYS`; the System Settings → "Purge obsolete data" action removes old batches/reports. Employee records are never hard-deleted.

**Recovery procedure**
1. Provision a fresh PostgreSQL and restore: `pg_restore --clean --create -d postgres veritrack-<date>.dump` (managed providers: "restore to new instance").
2. Restore `LOCAL_STORAGE_ROOT` from the file/object backup.
3. Point the app at the restored DB (`DATABASE_URL`), run `alembic upgrade head` (no-op if the dump is current), then redeploy.
4. Smoke-check: `/health/ready` must return 200 (DB + Redis), then log in as Master Admin and open one manager's dashboard.
5. Decide about in-flight Celery jobs: any batch marked PROCESSING/QUEUED at backup time should be re-triggered — files are still in storage, nothing is lost; simply reprocess the batch.

RPO/RTO targets to agree before launch: RPO ≤ 24h (nightly dump) or minutes (PITR); RTO ~1h including verification. Run a restore drill before go-live — an untested backup is not a backup.

---

## 📊 Module Status

| Module | Status |
|---|---|
| Backend APIs | ✅ Production Ready |
| Authentication + RBAC (incl. SSO) | ✅ Production Ready |
| Employee Management | ✅ Production Ready |
| Upload Engine | ✅ Production Ready |
| Compliance Engine | ✅ Production Ready |
| AI Recommendation Engine | ✅ Production Ready |
| OCR Document Processing | ✅ Production Ready |
| Report Generation | ✅ Production Ready |
| Email Notifications | ✅ Production Ready |
| Audit Logging | ✅ Production Ready |
| Security Layer | ✅ Production Ready |
| Docker Deployment | ✅ Production Ready |
| Frontend Dashboard | ✅ Complete (Private) |

---

## 🗺️ Roadmap

- [ ] Real-time notifications (WebSocket)
- [ ] Machine learning-based fraud detection
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Cloud deployment guides (AWS / GCP)
- [ ] Multi-tenant architecture

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](./LICENSE) file for details.

---

<div align="center">

🛡️ **VeriTrack AI — Automate compliance. Eliminate errors. Build trust.**

*Industry-grade backend. Production-ready architecture.*

</div>