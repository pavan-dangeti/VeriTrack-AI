"""Celery app (PROCESSING_MODE=celery): a batch's files run sequentially, batches run in parallel."""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "veritrack",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.worker_tasks"],
)

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # fair scheduling across managers' batches
    task_serializer="json",
    accept_content=["json"],
)
