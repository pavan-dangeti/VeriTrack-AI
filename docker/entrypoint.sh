#!/bin/sh
# Container entrypoint.
#   web    — migrate, sync the Master Admin from ADMIN_EMAIL / ADMIN_PASSWORD, serve the API
#   worker — Celery worker (PROCESSING_MODE=celery deployments)
set -e

case "${1:-web}" in
  web)
    alembic upgrade head
    python -m app.cli sync-master-admin
    python -m app.cli sync-demo-account
    exec uvicorn app.main:app \
      --host 0.0.0.0 --port "${PORT:-8000}" \
      --no-proxy-headers \
      --workers "${WEB_CONCURRENCY:-1}" \
      --timeout-keep-alive 30
    ;;
  worker)
    exec celery -A app.worker worker --loglevel=INFO --concurrency="${CELERY_CONCURRENCY:-2}"
    ;;
  *)
    exec "$@"
    ;;
esac
