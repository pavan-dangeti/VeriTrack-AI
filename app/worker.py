"""Celery application.

Sequential-per-batch: process_batch_task walks its files one at a time.
Parallel-across-managers: multiple workers pick different batches
concurrently. celery_task_always_eager=true runs tasks inline for tests/demo.
"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "veritrack",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.worker_tasks"],
)

celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=False,
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # fair scheduling across managers' batches
    task_serializer="json",
    accept_content=["json"],
)
