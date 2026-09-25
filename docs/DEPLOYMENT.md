# Deploying VeriTrack AI

Recommended topology: **frontend on Vercel, API + PostgreSQL on Render**.
The browser only ever talks to the Vercel domain; Vercel proxies `/api/*` to
Render, so the refresh cookie stays first-party (`SameSite=Strict`) and no
CORS is involved.

```
browser ──► https://<app>.vercel.app  ──(/api/* rewrite)──► https://veritrack-api.onrender.com
                     static React build                        FastAPI (Docker) ──► Render PostgreSQL
                                                                         └─► persistent disk / S3
```

## 1. Backend on Render

1. Push this repository to GitHub.
2. Render dashboard → **New → Blueprint** → select the repo. `render.yaml`
   creates:
   * `veritrack-api` — Docker web service (migrations run on every boot, the
     Master Admin is seeded once),
   * `veritrack-db` — managed PostgreSQL wired in as `DATABASE_URL`,
   * a 5 GB persistent disk for uploaded files and reports
     (`STORAGE_BACKEND=volume`).
3. Fill in the prompted variables:

   | Variable | Value |
   |---|---|
   | `SEED_ADMIN_EMAIL` | the first administrator's email |
   | `SEED_ADMIN_PASSWORD` | a strong password (change it after first login) |
   | `CORS_ORIGINS` | your Vercel URL, e.g. `https://veritrack.vercel.app` |

   `JWT_SECRET_KEY` is generated automatically.
4. Wait for the deploy; `https://veritrack-api.onrender.com/health/ready` must
   return `{"status":"ready"}`.

> **Instance size.** Measured in production mode: the API uses ≈ 390 MB with one
> OCR engine and ≈ 520 MB with two, and reads a sheet in ≈ 5–6 s per engine.
> `render.yaml` therefore uses the **Standard** plan (1 CPU, 2 GB) with
> `OCR_CONCURRENCY=1`; on **Pro** (2 CPU, 4 GB) set `OCR_CONCURRENCY=2`.
> Starter (512 MB) leaves no headroom and is not recommended.
>
> **No persistent disk?** Set `STORAGE_BACKEND=s3` with any S3-compatible bucket
> (`S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_ENDPOINT_URL` for R2/MinIO)
> and remove the `disk:` block.

## 2. Frontend on Vercel

1. Edit `vercel.json` and replace `https://veritrack-api.onrender.com` (two
   places) with your Render service URL. Commit and push.
2. Vercel → **Add New → Project** → import the repo. Leave *Root Directory* as
   the repository root — `vercel.json` already sets the install/build commands
   and `frontend/dist` as the output; `.vercelignore` keeps the Python backend
   out of the Vercel build.
3. Deploy, open the URL, sign in with the seeded administrator.

### Calling the API cross-origin instead (optional)

If you cannot use the rewrite, set `VITE_API_BASE_URL=https://<render-url>` in
Vercel, and on Render set `COOKIE_SAMESITE=none`, `CORS_ORIGINS=<vercel-url>` and
`TRUSTED_PROXY_HOPS=1`.

## Production settings reference

| Variable | Purpose |
|---|---|
| `ENVIRONMENT=production` | enables strict validation, secure cookies, HSTS, hides `/docs` |
| `PROCESSING_MODE` | `background` (default, no Redis) · `celery` (Redis + `worker` containers) |
| `OCR_CONCURRENCY` | parallel OCR engines per API process (≈ CPU cores) |
| `WEB_CONCURRENCY` | uvicorn worker processes |
| `TRUSTED_PROXY_HOPS` | proxies in front of the API: `2` for Vercel → Render (set in `render.yaml`), `1` for Render alone or the nginx container, `0` direct. Rate limits and the audit log use the address this many hops from the right of `X-Forwarded-For`, so clients cannot forge it. If you drop the Vercel rewrite and call Render directly, set it to `1`. |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | connection pool per process |
| `RATE_LIMIT_STORAGE_URI` | `redis://…` when running more than one API instance |
| `STORAGE_BACKEND`, `S3_*` | object storage for uploads/reports |
| `OUTBOUND_EMAIL_MODE=live` + `GRAPH_*` | real violation emails via Microsoft Graph |
| `M365_*` | Microsoft Entra ID single sign-on |

## Scaling out

* More users: raise the Render instance size, `WEB_CONCURRENCY` and
  `OCR_CONCURRENCY`; the job claims make multiple processes/replicas safe.
* Heavy OCR volume: set `PROCESSING_MODE=celery`, add Redis, and run the same
  image with the `worker` command (`docker-compose.yml` profile `celery`).
* Multiple API replicas: set `RATE_LIMIT_STORAGE_URI` to Redis and use S3
  storage so every replica sees the same files.

## Operations

* **Health**: `/health` (liveness), `/health/ready` (database, plus Redis when used).
* **Logs**: structured JSON on stdout; every line carries the `request_id`
  that is also returned in the `X-Request-ID` header and every error body.
* **Backups**: enable Render's automatic PostgreSQL backups; back up the disk
  or bucket alongside. Restore = restore the database, restore files, redeploy
  (migrations are idempotent).
* **Retention**: System Settings → *Purge obsolete data* removes batches and
  reports older than `RETENTION_DAYS`; employee records are never hard-deleted.
