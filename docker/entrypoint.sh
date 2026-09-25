#!/bin/sh
# Container entrypoint.
#   web    — migrate, seed the Master Admin once, serve the API
#   worker — Celery worker (PROCESSING_MODE=celery deployments)
set -e

case "${1:-web}" in
  web)
    alembic upgrade head
    if [ -n "$SEED_ADMIN_PASSWORD" ]; then
      python -m app.cli create-master-admin --if-not-exists
    else
      echo "SEED_ADMIN_PASSWORD not set — skipping Master Admin bootstrap" >&2
    fi
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
